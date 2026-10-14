"""Dormant Oracle facts do not infer a write target from an expression's sources."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject
from dblift.db.plugins.oracle.quirks import OracleQuirks


@pytest.mark.parametrize(
    "sql,operation",
    [
        ("DELETE FROM (SELECT x FROM t WHERE x=1)", "DELETE"),
        ("DELETE FROM (SELECT x FROM t WHERE x=1) WHERE x<3", "DELETE"),
        ("DELETE FROM (SELECT t.x FROM t JOIN u ON t.id=u.id)", "DELETE"),
        ("DELETE FROM ONLY(t) WHERE x=1", "DELETE"),
        ("DELETE FROM TABLE(SELECT items FROM orders WHERE id=1) WHERE x=2", "DELETE"),
        ("UPDATE TABLE(SELECT items FROM orders WHERE id=1) SET x=2", "UPDATE"),
        ("INSERT INTO TABLE(SELECT items FROM orders WHERE id=1) VALUES (2)", "INSERT"),
        ("DELETE FROM TABLE(SELECT items FROM orders) WHERE x=", "DELETE"),
        ("UPDATE ONLY(t) SET x=", "UPDATE"),
        ("UPDATE t PARTITION (p1) SET x=1", "UPDATE"),
        ("DELETE FROM t SUBPARTITION (sp1)", "DELETE"),
        ("INSERT INTO t PARTITION (p1) VALUES (1)", "INSERT"),
    ],
)
def test_oracle_unproven_mutation_targets_have_no_mutation_payload(sql, operation):
    facts = read_statement_facts(sql, dialect="oracle")

    assert facts.opaque
    assert facts.diagnostic
    assert facts.error is None
    assert facts.operation == operation
    assert facts.kind == "DML"
    assert facts.objects == ()
    assert facts.target is None
    assert facts.target_sql is None
    assert facts.predicate is None
    assert facts.events is None
    assert facts.affected_columns == ()


@pytest.mark.parametrize(
    "sql,operation,target,target_sql,predicate,columns",
    [
        ("DELETE FROM t WHERE x=1", "DELETE", "t", "t", "x = 1", ()),
        ("DELETE t WHERE x=1", "DELETE", "t", "t", "x = 1", ()),
        ("DELETE FROM t a WHERE a.x=1", "DELETE", "t", "t a", "a.x = 1", ()),
        ('DELETE FROM t "PARTITION" WHERE x=1', "DELETE", "t", 't "PARTITION"', "x = 1", ()),
        ("UPDATE t a SET a.x=2 WHERE a.id=1", "UPDATE", "t", "t a", "a.id = 1", ("x",)),
        ("INSERT INTO t (x) VALUES (1)", "INSERT", "t", "t", None, ()),
        (
            'UPDATE "Sales"."Order Items" SET "Value"=1 WHERE "Id"=2',
            "UPDATE",
            "Sales.Order Items",
            '"Sales"."Order Items"',
            '"Id" = 2',
            ("Value",),
        ),
    ],
)
def test_oracle_direct_mutation_targets_keep_their_facts(
    sql, operation, target, target_sql, predicate, columns
):
    facts = read_statement_facts(sql, dialect="oracle")

    assert not facts.opaque
    assert facts.target == target
    assert facts.target_sql == target_sql
    assert facts.predicate == predicate
    assert facts.events == frozenset({operation})
    assert facts.affected_columns == columns


def test_oracle_predicate_subquery_does_not_make_a_direct_target_opaque():
    facts = read_statement_facts("DELETE FROM t WHERE id IN (SELECT id FROM s)", dialect="oracle")

    assert not facts.opaque
    assert facts.target == "t"
    assert facts.predicate == "id IN (SELECT id FROM s)"
    assert facts.objects == (
        NamedObject("t", SqlObjectType.TABLE, "altered"),
        NamedObject("s", SqlObjectType.TABLE, "referenced"),
    )


def test_oracle_statement_facts_remain_dormant():
    assert not OracleQuirks().supports_statement_facts
