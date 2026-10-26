"""Safety boundaries for statement facts with incomplete upstream grammar."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.statement_facts import NamedObject, SqlglotStatementFactsReader
from dblift.db.plugins.postgresql.statement_facts import PostgresqlStatementFactsReader
from dblift.db.provider_registry import ProviderRegistry


def _read(plugin, sql):
    return ProviderRegistry.get_quirks(plugin).statement_facts_reader().read(sql)


def test_yugabyte_has_its_own_sqlglot_facts_reader():
    quirks = ProviderRegistry.get_quirks("yugabytedb")
    reader = quirks.statement_facts_reader()

    assert isinstance(reader, SqlglotStatementFactsReader)
    assert type(reader) is not SqlglotStatementFactsReader
    assert vars(type(quirks)).get("statement_facts_class") is type(reader)
    assert reader.dialect == "postgres"
    assert type(ProviderRegistry.get_quirks("postgresql").statement_facts_reader()) is (
        PostgresqlStatementFactsReader
    )
    assert type(ProviderRegistry.get_quirks("cockroachdb").statement_facts_reader()) is (
        SqlglotStatementFactsReader
    )


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE INDEX NONCONCURRENTLY ix ON t(id)",
        "CREATE INDEX NONCONCURRENTLY ON t(id)",
        "CREATE UNIQUE INDEX NONCONCURRENTLY ux ON t(id)",
        "CREATE UNIQUE INDEX NONCONCURRENTLY ON t(id)",
        "create unique index nonconcurrently ux on t(id)",
        "CREATE /* head */ INDEX /* modifier */ NONCONCURRENTLY ix ON t(id)",
        "CREATE /* head */ UNIQUE /* head */ INDEX /* modifier */ NONCONCURRENTLY ux ON t(id)",
        "CREATE /* outer /* inner */ tail */ INDEX NONCONCURRENTLY ix ON t(id)",
    ],
)
def test_yugabyte_nonconcurrently_never_invents_an_index_identity(sql):
    facts = _read("yugabytedb", sql)

    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert facts.opaque and facts.diagnostic and facts.error is None
    assert facts.objects == ()
    assert (facts.indexed_table, facts.indexed_columns) == (None, None)
    assert (facts.target, facts.predicate, facts.events) == (None, None, None)


@pytest.mark.parametrize(
    ("sql", "index_name"),
    [
        ("CREATE INDEX ix ON t(id)", "ix"),
        ("CREATE INDEX CONCURRENTLY ix ON t(id)", "ix"),
        ("CREATE UNIQUE INDEX CONCURRENTLY ux ON t(id)", "ux"),
        ('CREATE INDEX "NONCONCURRENTLY" ON t(id)', "NONCONCURRENTLY"),
        ('CREATE INDEX /* quoted */ "NONCONCURRENTLY" ON t(id)', "NONCONCURRENTLY"),
        ("CREATE /* outer /* inner */ tail */ INDEX ix ON t(id)", "ix"),
        (
            'CREATE /* outer /* inner */ tail */ INDEX "NONCONCURRENTLY" ON t(id)',
            "NONCONCURRENTLY",
        ),
        ("CrEaTe /* head */ InDeX ix ON t(id)", "ix"),
    ],
)
def test_yugabyte_plain_and_quoted_index_identities_are_preserved(sql, index_name):
    facts = _read("yugabytedb", sql)

    assert (facts.operation, facts.kind, facts.opaque) == ("CREATE", "DDL", False)
    assert facts.objects == (
        NamedObject(index_name, SqlObjectType.INDEX, "created"),
        NamedObject("t", SqlObjectType.TABLE, "referenced"),
    )
    assert (facts.indexed_table, facts.indexed_columns) == ("t", ("id",))


def test_yugabyte_nonconcurrently_outside_the_index_head_is_an_ordinary_column():
    facts = _read("yugabytedb", "CREATE INDEX ix ON t(nonconcurrently)")

    assert facts.objects == (
        NamedObject("ix", SqlObjectType.INDEX, "created"),
        NamedObject("t", SqlObjectType.TABLE, "referenced"),
    )
    assert facts.indexed_columns == ("nonconcurrently",)
    assert not facts.opaque


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE t SET id = 2 WHERE id = 1",
        "/* unclosed",
        'CREATE INDEX "unclosed ON t(id)',
        r"\dt",
        "CREATE INDEX ix ON t(id)\x00",
    ],
)
def test_yugabyte_unrelated_inputs_preserve_postgres_reader_facts(sql):
    expected = SqlglotStatementFactsReader("postgres").read(sql)

    assert _read("yugabytedb", sql) == expected


@pytest.mark.parametrize("plugin", ["postgresql", "cockroachdb"])
@pytest.mark.parametrize(
    "sql",
    ["CREATE INDEX nonconcurrently ON t(id)", "CREATE UNIQUE INDEX nonconcurrently ON t(id)"],
)
def test_postgres_family_keeps_nonconcurrently_as_an_ordinary_index_name(plugin, sql):
    facts = _read(plugin, sql)

    assert facts.objects == (
        NamedObject("nonconcurrently", SqlObjectType.INDEX, "created"),
        NamedObject("t", SqlObjectType.TABLE, "referenced"),
    )
    assert (facts.indexed_table, facts.indexed_columns, facts.opaque) == ("t", ("id",), False)


@pytest.mark.parametrize("plugin", ["mariadb", "mysql"])
def test_alter_sequence_names_its_sequence_through_each_mysql_plugin(plugin):
    # MariaDB 11.8.8 runs it (4091 when the sequence is missing); MySQL rejects it (1064). The
    # reader is shared, so both plugins name the sequence from the head.
    facts = _read(plugin, "ALTER SEQUENCE users_seq RESTART WITH 100")

    assert (facts.operation, facts.kind) == ("ALTER", "DDL")
    assert facts.objects == (NamedObject("users_seq", SqlObjectType.SEQUENCE, "altered"),)


@pytest.mark.parametrize(
    ("plugin", "sql", "operation"),
    [
        ("postgresql", "CREATE FOREIGN TABLE ft PARTITION OF parent DEFAULT SERVER s", "CREATE"),
        ("postgresql", "ALTER FOREIGN TABLE ft SET SCHEMA ns", "ALTER"),
        ("postgresql", "DROP FOREIGN TABLE ft*", "DROP"),
    ],
)
def test_unsupported_ddl_keeps_names_opaque_until_the_grammar_supports_it(plugin, sql, operation):
    facts = _read(plugin, sql)

    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert facts.opaque and facts.diagnostic and facts.error is None
    assert facts.objects == ()
    assert (facts.indexed_table, facts.indexed_columns, facts.target, facts.events) == (
        None,
        None,
        None,
        None,
    )
