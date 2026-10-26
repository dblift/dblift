"""A parsed or fallback head cannot discard malformed parts of an object name."""

import pytest

from dblift.db.provider_registry import ProviderRegistry


@pytest.mark.parametrize("dialect", ("postgresql", "mysql", "sqlite", "duckdb"))
@pytest.mark.parametrize(
    "sql",
    (
        "CREATE TABLE db..t (id INT)",
        'ALTER TABLE a."".t ADD COLUMN x INT',
        "INSERT INTO db..t VALUES (1)",
        "UPDATE .t SET x = 1",
        'DELETE FROM a."".t',
        "SELECT * FROM db..t",
        "DROP TABLE t*",
    ),
)
def test_malformed_object_name_is_unread(dialect, sql):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts(sql)

    assert facts.objects == ()
    assert facts.target is None
    assert facts.opaque and facts.diagnostic


@pytest.mark.parametrize("dialect", ("postgresql", "mysql", "sqlite", "duckdb"))
@pytest.mark.parametrize(
    "sql",
    (
        "INSERT INTO t* VALUES (1)",
        "UPDATE t* SET x = 1",
        "DELETE FROM t* WHERE x = 1",
        "SELECT * FROM t*",
        "SELECT * FROM t, .u",
        "SELECT * FROM (.t)",
    ),
)
def test_parsed_name_with_attached_junk_or_dropped_prefix_is_unread(dialect, sql):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts(sql)

    assert facts.objects == ()
    assert facts.target is None
    assert facts.opaque and facts.diagnostic


@pytest.mark.parametrize("dialect", ("postgresql", "mysql", "sqlite", "duckdb"))
def test_index_target_with_dropped_prefix_is_unread(dialect):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts("CREATE INDEX ix ON .t(a)")

    assert facts.objects == ()
    assert facts.target is None
    assert facts.opaque and facts.diagnostic


@pytest.mark.parametrize("dialect", ("postgresql", "mysql"))
@pytest.mark.parametrize("sql", ("CREATE SCHEMA .s", "DROP SCHEMA .s"))
def test_schema_name_with_dropped_prefix_is_unread(dialect, sql):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts(sql)

    assert facts.objects == ()
    assert facts.opaque and facts.diagnostic


@pytest.mark.parametrize(
    "sql",
    (
        "CREATE SCHEMA .s",
        "DROP SCHEMA .s",
        "CREATE DATABASE .s",
        "DROP DATABASE .s",
        "DROP INDEX .ix",
        "CREATE SEQUENCE .s",
        "DROP SEQUENCE .s",
        "DROP FUNCTION .f",
        "DROP PROCEDURE .p",
        "DROP TRIGGER .tr",
    ),
)
def test_mariadb_leading_dot_is_not_a_nonrelation_name(sql):
    facts = ProviderRegistry.get_quirks("mariadb").statement_facts(sql)

    assert facts.objects == ()
    assert facts.opaque and facts.diagnostic


@pytest.mark.parametrize("dialect", ("postgresql", "mysql", "sqlite", "duckdb"))
def test_ordinary_qualified_name_remains_readable(dialect):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts("INSERT INTO s.t VALUES (1)")

    assert [(obj.schema, obj.name) for obj in facts.objects] == [("s", "t")]
    assert facts.target == "s.t"
    assert not facts.opaque


@pytest.mark.parametrize(
    "dialect,quote",
    (("postgresql", '"'), ("mysql", "`"), ("sqlite", '"'), ("duckdb", '"')),
)
def test_quoted_dots_keep_their_written_identity(dialect, quote):
    quirks = ProviderRegistry.get_quirks(dialect)
    qualified = quirks.statement_facts(f"CREATE TABLE {quote}s{quote}.{quote}t{quote} (id INT)")
    embedded = quirks.statement_facts(f"CREATE TABLE {quote}s.t{quote} (id INT)")

    assert [(obj.schema, obj.name) for obj in qualified.objects] == [("s", "t")]
    assert [(obj.schema, obj.name) for obj in embedded.objects] == [(None, "s.t")]
    assert not qualified.opaque and not embedded.opaque


def test_mariadb_leading_dot_uses_the_default_database():
    facts = ProviderRegistry.get_quirks("mariadb").statement_facts("SELECT * FROM .t")

    assert [(obj.schema, obj.name) for obj in facts.objects] == [(None, "t")]
    assert not facts.opaque


@pytest.mark.parametrize(
    "sql,names",
    (
        ("CREATE TABLE .t (id INT)", ("t",)),
        ("DROP TABLE .t", ("t",)),
        ("CREATE VIEW .v AS SELECT 1", ("v",)),
        ("DROP VIEW .v", ("v",)),
        ("CREATE INDEX ix ON .t(a)", ("ix", "t")),
        ("SELECT * FROM t JOIN .u ON t.id=u.id", ("t", "u")),
        ("INSERT INTO .t VALUES (1)", ("t",)),
        ("UPDATE .t SET x=1", ("t",)),
        ("DELETE FROM .t", ("t",)),
        ("ALTER TABLE .t ADD COLUMN x INT", ("t",)),
        ("TRUNCATE TABLE .t", ("t",)),
    ),
)
def test_mariadb_leading_dot_relation_names_remain_readable(sql, names):
    facts = ProviderRegistry.get_quirks("mariadb").statement_facts(sql)

    assert tuple(obj.name for obj in facts.objects) == names
    assert not facts.opaque


def test_sqlserver_omitted_schema_does_not_publish_a_wrong_identity():
    facts = ProviderRegistry.get_quirks("sqlserver").statement_facts("SELECT * FROM db..t")

    assert facts.objects == ()
    assert facts.opaque and facts.diagnostic
