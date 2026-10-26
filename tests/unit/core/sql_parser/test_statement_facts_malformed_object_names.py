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


def test_sqlserver_omitted_schema_does_not_publish_a_wrong_identity():
    facts = ProviderRegistry.get_quirks("sqlserver").statement_facts("SELECT * FROM db..t")

    assert facts.objects == ()
    assert facts.opaque and facts.diagnostic
