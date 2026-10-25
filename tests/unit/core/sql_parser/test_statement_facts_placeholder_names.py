"""Bind placeholders cannot prove an object identity."""

import pytest

from dblift.db.provider_registry import ProviderRegistry


@pytest.mark.parametrize(
    "dialect, sql",
    [
        ("postgresql", "DROP TABLE ?"),
        ("cockroachdb", "CREATE TABLE s.? (id INT)"),
        ("redshift", "DROP TABLE %s"),
        ("mysql", "ALTER TABLE ? ADD COLUMN x INT"),
        ("mariadb", "INSERT INTO ? VALUES (1)"),
        ("oracle", "DROP TABLE $1"),
        ("sqlserver", "DROP TABLE $1"),
        ("sqlite", "DROP TABLE $1"),
        ("duckdb", "DROP TABLE ?"),
        ("snowflake", "DROP TABLE ?"),
    ],
)
def test_placeholder_in_object_name_is_unread(dialect, sql):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts(sql)
    assert facts.objects == ()
    assert facts.opaque and facts.diagnostic


@pytest.mark.parametrize("dialect", ("postgresql", "mysql", "sqlite"))
def test_value_placeholder_does_not_hide_a_named_target(dialect):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts("INSERT INTO t VALUES (?)")
    assert [obj.name.lower() for obj in facts.objects] == ["t"]


@pytest.mark.parametrize("dialect", ("postgresql", "mysql", "sqlite"))
def test_quoted_question_mark_remains_a_written_name(dialect):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts('DROP TABLE "?"')
    assert [obj.name for obj in facts.objects] == ["?"]


@pytest.mark.parametrize("dialect", ("mysql", "mariadb"))
def test_mysql_dollar_digit_remains_an_unquoted_name(dialect):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts("INSERT INTO $1 VALUES ('$1', ?)")
    assert [obj.name for obj in facts.objects] == ["$1"]
    assert not facts.opaque


@pytest.mark.parametrize(
    "dialect, quoted_name",
    (("oracle", '"$1"'), ("sqlite", '"$1"'), ("sqlserver", "[$1]")),
)
def test_quoted_dollar_digit_remains_a_written_name(dialect, quoted_name):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts(f"DROP TABLE {quoted_name}")
    assert [obj.name for obj in facts.objects] == ["$1"]
