"""Dormant MySQL-family DROP INDEX facts retain their proven table relation."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject
from dblift.db.plugins.mariadb.quirks import MariadbQuirks
from dblift.db.plugins.mysql.quirks import MysqlQuirks


@pytest.mark.parametrize(
    "sql,index_name,table_name",
    [
        ("DROP INDEX idx ON t", "idx", "t"),
        ("DROP INDEX `a``b` ON `t``x`", "a`b", "t`x"),
        ("DROP INDEX idx ON `t.x`", "idx", "t.x"),
    ],
)
def test_mysql_drop_index_keeps_the_on_table_relation(sql, index_name, table_name):
    facts = read_statement_facts(sql, dialect="mysql")
    index = NamedObject(index_name, SqlObjectType.INDEX, "dropped")

    assert not facts.opaque
    assert (facts.operation, facts.kind) == ("DROP", "DDL")
    assert facts.objects == (index, NamedObject(table_name, SqlObjectType.TABLE, "referenced"))
    assert facts.affected_objects == (index,)
    assert facts.indexed_table == table_name
    assert facts.indexed_columns is None
    assert facts.target is None
    assert facts.target_sql is None
    assert facts.events is None


@pytest.mark.parametrize(
    "sql",
    [
        "DROP INDEX idx ON db.t",
        "DROP INDEX `idx` ON `Sales`.`Order Items`",
        "DROP INDEX idx ON t ALGORITHM=INPLACE LOCK=NONE",
        "DROP INDEX idx ON t NOWAIT",
        "DROP INDEX idx ON t WAIT 1",
        "DROP INDEX idx ON (SELECT 1)",
    ],
)
def test_mysql_unproven_drop_index_relations_remain_opaque(sql):
    facts = read_statement_facts(sql, dialect="mysql")

    assert facts.opaque
    assert facts.diagnostic
    assert facts.indexed_table is None
    assert all(obj.type != SqlObjectType.TABLE for obj in facts.objects)


@pytest.mark.parametrize(
    "target", ["'t'", "''", "``", '"t"', "123", "1e3", "NULL", "TRUE", "DEFAULT"]
)
def test_mysql_drop_index_pseudo_identifiers_do_not_prove_a_table(target):
    facts = read_statement_facts(f"DROP INDEX idx ON {target}", dialect="mysql")

    assert facts.opaque
    assert facts.indexed_table is None
    assert all(obj.type != SqlObjectType.TABLE for obj in facts.objects)


@pytest.mark.parametrize("option", ["CASCADE", "RESTRICT", "PURGE", "SYNC"])
def test_mysql_drop_index_unmodelled_options_do_not_prove_a_relation(option):
    facts = read_statement_facts(f"DROP INDEX idx ON t {option}", dialect="mysql")

    assert facts.opaque
    assert facts.indexed_table is None
    assert all(obj.type != SqlObjectType.TABLE for obj in facts.objects)


@pytest.mark.parametrize("index", ["``", "'idx'", '"idx"', "NULL"])
def test_mysql_drop_index_unproven_index_does_not_prove_a_relation(index):
    facts = read_statement_facts(f"DROP INDEX {index} ON t", dialect="mysql")

    assert facts.opaque
    assert all(obj.type != SqlObjectType.TABLE for obj in facts.objects)
    assert facts.indexed_table is None


@pytest.mark.parametrize("index", ["``.idx", "``.``.idx"])
def test_mysql_drop_index_empty_qualifiers_remain_opaque(index):
    facts = read_statement_facts(f"DROP INDEX {index} ON t", dialect="mysql")

    assert facts.opaque
    assert facts.indexed_table is None
    assert all(obj.type != SqlObjectType.TABLE for obj in facts.objects)


@pytest.mark.parametrize("dialect", ["sqlite", "duckdb", "postgres", "oracle", "tsql"])
def test_other_dialect_drop_indexes_do_not_gain_a_mysql_relation(dialect):
    facts = read_statement_facts("DROP INDEX idx", dialect=dialect)

    assert facts.objects == (NamedObject("idx", SqlObjectType.INDEX, "dropped"),)
    assert facts.indexed_table is None


@pytest.mark.parametrize("quirks_class", [MysqlQuirks, MariadbQuirks])
def test_mysql_family_drop_index_preparation_keeps_facts_dormant(quirks_class):
    assert not quirks_class().supports_statement_facts


def test_mysql_create_index_relation_is_unchanged():
    facts = read_statement_facts("CREATE INDEX idx ON t(id)", dialect="mysql")

    assert facts.objects == (
        NamedObject("idx", SqlObjectType.INDEX, "created"),
        NamedObject("t", SqlObjectType.TABLE, "referenced"),
    )
    assert facts.indexed_table == "t"
    assert facts.indexed_columns == ("id",)
