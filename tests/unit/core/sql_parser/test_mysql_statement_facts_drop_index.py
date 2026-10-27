"""Dormant MySQL-family DROP INDEX facts retain their proven table relation."""

import pytest
from sqlglot import exp

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import (
    _mysql_identifier_is_proven,
    _mysql_on_table_name,
    read_statement_facts,
)
from dblift.core.sql_parser.statement_facts import (
    NamedObject,
    SqlglotStatementFactsReader,
    StatementFacts,
)
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


_DROP_INDEX_SPACED = [
    "DROP INDEX idx ON t{c}",
    "DROP INDEX idx ON {c}t",
    "DROP INDEX idx{c} ON t",
    "DROP INDEX {c}idx ON t",
]


@pytest.mark.parametrize("semicolon", ["", ";"])
@pytest.mark.parametrize("template", _DROP_INDEX_SPACED)
@pytest.mark.parametrize("char", ["\u00a0", "\u0085", "\u2003", "\u2028", "\u3000"])
def test_mysql_drop_index_non_ascii_space_beside_a_name_is_not_proven(char, template, semicolon):
    # sqlglot skips these as whitespace; MySQL/MariaDB read them as part of the name.
    facts = read_statement_facts(template.format(c=char) + semicolon, dialect="mysql")

    assert facts.opaque
    assert facts.diagnostic
    assert facts.indexed_table is None


@pytest.mark.parametrize("semicolon", ["", ";"])
@pytest.mark.parametrize("template", _DROP_INDEX_SPACED)
@pytest.mark.parametrize("char", ["\x0b", "\x0c"])
def test_mysql_drop_index_vertical_tab_and_form_feed_are_real_whitespace(char, template, semicolon):
    facts = read_statement_facts(template.format(c=char) + semicolon, dialect="mysql")

    assert not facts.opaque
    assert facts.indexed_table == "t"


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
    """A bare T-SQL index has no proven owner; other dialects retain their reading."""
    facts = read_statement_facts("DROP INDEX idx", dialect=dialect)

    if dialect == "tsql":
        assert (facts.operation, facts.kind) == ("DROP", "DDL")
        assert facts.objects == () and facts.indexed_table is None
        assert facts.opaque and facts.diagnostic == "tsql index relation is opaque"
        return
    name = "IDX" if dialect in {"oracle", "snowflake"} else "idx"  # these fold unquoted names
    assert facts == StatementFacts(
        "DROP", "DDL", (NamedObject(name, SqlObjectType.INDEX, "dropped"),)
    )


@pytest.mark.parametrize("sql", ["DROP INDEX idx ON t", "DROP INDEX idx ON s.t"])
def test_tsql_drop_index_on_relation_keeps_its_modelled_index(sql):
    facts = read_statement_facts(sql, dialect="tsql")

    schema = "s" if sql.endswith("s.t") else None
    table = "s.t" if schema else "t"
    assert facts == StatementFacts(
        "DROP",
        "DDL",
        (
            NamedObject("idx", SqlObjectType.INDEX, "dropped", schema),
            NamedObject("t", SqlObjectType.TABLE, "referenced", schema),
        ),
        indexed_table=table,
    )


@pytest.mark.parametrize(
    "dialect", ["sqlite", "duckdb", "postgres", "oracle", "redshift", "snowflake"]
)
@pytest.mark.parametrize("sql", ["DROP INDEX idx ON t", "DROP INDEX idx ON s.t"])
def test_drop_index_on_relation_without_modelled_grammar_stays_opaque(dialect, sql):
    facts = read_statement_facts(sql, dialect=dialect)

    name = "IDX" if dialect in {"oracle", "snowflake"} else "idx"  # these fold unquoted names
    assert facts.opaque
    assert facts.objects == (NamedObject(name, SqlObjectType.INDEX, "dropped"),)
    assert facts.indexed_table is None


def test_mysql_drop_index_if_exists_keeps_the_on_table_relation():
    facts = read_statement_facts("DROP INDEX IF EXISTS idx ON t", dialect="mysql")

    assert not facts.opaque
    assert facts.indexed_table == "t"
    assert facts.objects == (
        NamedObject("idx", SqlObjectType.INDEX, "dropped"),
        NamedObject("t", SqlObjectType.TABLE, "referenced"),
    )


@pytest.mark.parametrize("quirks_class", [MysqlQuirks, MariadbQuirks])
def test_mysql_family_drop_index_preparation_runs_with_facts_active(quirks_class):
    assert quirks_class().supports_statement_facts
    assert issubclass(quirks_class().statement_facts_class, SqlglotStatementFactsReader)


def test_mysql_create_index_relation_is_unchanged():
    facts = read_statement_facts("CREATE INDEX idx ON t(id)", dialect="mysql")

    assert facts.objects == (
        NamedObject("idx", SqlObjectType.INDEX, "created"),
        NamedObject("t", SqlObjectType.TABLE, "referenced"),
    )
    assert facts.indexed_table == "t"
    assert facts.indexed_columns == ("id",)


def _identifier_at(sql: str, name: str) -> exp.Identifier:
    identifier = exp.to_identifier(name)
    start = sql.index(name)
    identifier.meta["start"], identifier.meta["end"] = start, start + len(name) - 1
    return identifier


@pytest.mark.parametrize(
    "wrap",
    [
        pytest.param(lambda identifier: identifier, id="bare identifier"),
        pytest.param(lambda identifier: exp.Table(this=identifier), id="table wrapper"),
    ],
)
def test_on_table_name_reads_either_sqlglot_shape(wrap):
    """sqlglot 30.18 leaves the ``ON`` name bare; later versions wrap it in a Table."""
    sql = "DROP INDEX idx ON t"
    on = exp.OnProperty(this=wrap(_identifier_at(sql, "t")))
    assert _mysql_on_table_name(on, sql) == "t"


def test_on_table_name_refuses_a_table_wrapper_with_more_than_a_name():
    sql = "DROP INDEX idx ON s.t"
    table = exp.Table(this=_identifier_at(sql, "t"), db=exp.to_identifier("s"))
    assert _mysql_on_table_name(exp.OnProperty(this=table), sql) is None


def test_identifier_without_source_positions_is_not_proven():
    assert _mysql_identifier_is_proven(exp.to_identifier("t"), "DROP INDEX idx ON t") is False
