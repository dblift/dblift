"""Dormant MySQL facts refuse mutations without a proven single target."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject
from dblift.db.plugins.mariadb.quirks import MariadbQuirks
from dblift.db.plugins.mysql.quirks import MysqlQuirks


@pytest.mark.parametrize(
    "sql,operation",
    [
        ("UPDATE t JOIN u ON t.id=u.id SET t.x=1,u.y=2 WHERE t.id=3", "UPDATE"),
        ("UPDATE t a JOIN u b ON a.id=b.id SET a.x=1,b.y=2", "UPDATE"),
        ("UPDATE t,u SET t.x=1,u.y=2", "UPDATE"),
        ("UPDATE t JOIN u ON t.id=u.id SET x=1", "UPDATE"),
        ("UPDATE t JOIN u ON t.id=u.id SET u.y=2", "UPDATE"),
        ("DELETE t,u FROM t JOIN u ON t.id=u.id WHERE t.id=3", "DELETE"),
        ("DELETE a,b FROM t a JOIN u b ON a.id=b.id", "DELETE"),
        ("DELETE FROM t,u USING t JOIN u ON t.id=u.id", "DELETE"),
    ],
)
def test_mysql_unresolved_mutation_targets_are_opaque(sql, operation):
    facts = read_statement_facts(sql, dialect="mysql")

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
    "sql,operation,columns",
    [
        ("UPDATE t JOIN u ON t.id=u.id SET t.x=1 WHERE t.id=3", "UPDATE", ("x",)),
        ("UPDATE t a JOIN u b ON a.id=b.id SET a.x=1", "UPDATE", ("x",)),
        ("UPDATE t SET x=1", "UPDATE", ("x",)),
        ("DELETE t FROM t JOIN u ON t.id=u.id", "DELETE", ()),
        ("DELETE a FROM t a JOIN u b ON a.id=b.id", "DELETE", ()),
        ("DELETE FROM t USING t JOIN u ON t.id=u.id", "DELETE", ()),
    ],
)
def test_mysql_proven_single_target_mutations_keep_their_facts(sql, operation, columns):
    facts = read_statement_facts(sql, dialect="mysql")

    assert not facts.opaque
    assert facts.target == "t"
    assert facts.affected_objects == (NamedObject("t", SqlObjectType.TABLE, "altered"),)
    assert facts.events == frozenset({operation})
    assert facts.affected_columns == columns


def test_mysql_upsert_keeps_insert_and_update_events():
    facts = read_statement_facts(
        "INSERT INTO t (id,x) VALUES (1,2) ON DUPLICATE KEY UPDATE x=3", dialect="mysql"
    )

    assert not facts.opaque
    assert facts.target == "t"
    assert facts.events == frozenset({"INSERT", "UPDATE"})
    assert facts.affected_columns == ("x",)


@pytest.mark.parametrize("quirks_class", [MysqlQuirks, MariadbQuirks])
def test_mysql_and_mariadb_facts_remain_dormant(quirks_class):
    quirks = quirks_class()

    assert quirks.sqlglot_dialect == "mysql"
    assert not quirks.supports_statement_facts


@pytest.mark.parametrize("dialect", ["sqlite", "duckdb", "postgres", "oracle", "tsql"])
def test_other_dialect_single_target_updates_keep_their_facts(dialect):
    facts = read_statement_facts("UPDATE t SET x=1 WHERE id=3", dialect=dialect)

    assert not facts.opaque
    assert facts.target == "t"
    assert facts.events == frozenset({"UPDATE"})
    assert facts.affected_columns == ("x",)
