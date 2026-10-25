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


@pytest.mark.parametrize(
    "dialect, marker",
    (
        ("postgresql", "?"),
        ("postgresql", "%s"),
        ("mysql", "?"),
        ("sqlite", "?"),
        ("duckdb", "?"),
        ("redshift", "?"),
        ("snowflake", "?"),
        ("oracle", "$1"),
        ("sqlite", "$1"),
        ("sqlserver", "$1"),
    ),
)
def test_placeholder_index_name_leaves_all_objects_unread(dialect, marker):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts(f"CREATE INDEX {marker} ON t (id)")
    assert facts.objects == ()
    assert facts.opaque and facts.diagnostic


@pytest.mark.parametrize(
    "dialect, quoted_name",
    (("postgresql", '"?"'), ("mysql", "`$1`"), ("sqlite", '"$1"')),
)
def test_quoted_index_name_remains_written(dialect, quoted_name):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts(
        f"CREATE INDEX {quoted_name} ON t (id)"
    )
    assert [obj.name for obj in facts.objects] == [quoted_name[1:-1], "t"]


def test_mysql_unquoted_dollar_digit_index_remains_written():
    facts = ProviderRegistry.get_quirks("mysql").statement_facts("CREATE INDEX $1 ON t (id)")
    assert [obj.name for obj in facts.objects] == ["$1", "t"]


@pytest.mark.parametrize(
    "dialect, sql",
    (
        ("sqlite", "CREATE TRIGGER $1 AFTER INSERT ON t BEGIN SELECT 1; END"),
        ("oracle", "CREATE SYNONYM $1 FOR t"),
        ("oracle", "DROP SYNONYM $1"),
        ("oracle", "CREATE TRIGGER $1 AFTER INSERT ON t BEGIN SELECT 1; END"),
    ),
)
def test_placeholder_fallback_head_has_no_object(dialect, sql):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts(sql)
    assert facts.objects == ()
    assert facts.opaque and facts.diagnostic


@pytest.mark.parametrize("dialect", ("postgresql", "cockroachdb", "redshift", "duckdb"))
@pytest.mark.parametrize(
    "sql",
    (
        "DROP TABLE $1",
        "CREATE INDEX $1 ON t (id)",
        "INSERT INTO $1 VALUES (1)",
        "CREATE VIEW $1 AS SELECT 1",
    ),
)
def test_positional_parameter_cannot_name_an_object(dialect, sql):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts(sql)
    assert facts.objects == ()
    assert facts.opaque and facts.diagnostic


def test_snowflake_positional_parameter_cannot_name_an_index():
    facts = ProviderRegistry.get_quirks("snowflake").statement_facts("CREATE INDEX $1 ON t (id)")
    assert facts.objects == ()
    assert facts.opaque and facts.diagnostic


@pytest.mark.parametrize("dialect", ("postgresql", "cockroachdb", "redshift", "duckdb"))
def test_positional_parameter_cannot_name_a_trigger(dialect):
    sql = "CREATE TRIGGER $1 AFTER INSERT ON t FOR EACH ROW EXECUTE FUNCTION f()"
    facts = ProviderRegistry.get_quirks(dialect).statement_facts(sql)
    assert facts.objects == ()
    assert facts.opaque and facts.diagnostic


@pytest.mark.parametrize(
    "dialect", ("postgresql", "cockroachdb", "redshift", "duckdb", "sqlite", "mysql")
)
def test_anonymous_placeholder_cannot_name_a_trigger(dialect):
    sql = "CREATE TRIGGER ? AFTER INSERT ON t FOR EACH ROW EXECUTE FUNCTION f()"
    facts = ProviderRegistry.get_quirks(dialect).statement_facts(sql)
    assert facts.objects == ()
    assert facts.opaque and facts.diagnostic


def test_duckdb_at_name_is_not_hidden_by_a_value_parameter():
    sql = "SELECT COUNT(*) INTO @n FROM t WHERE id = $1"
    facts = ProviderRegistry.get_quirks("duckdb").statement_facts(sql)
    assert [obj.name for obj in facts.objects] == ["n", "t"]
    assert not facts.opaque


@pytest.mark.parametrize("dialect", ("postgresql", "redshift", "duckdb"))
@pytest.mark.parametrize(
    "sql", ("DROP TABLE IF EXISTS $1", "CREATE TABLE IF NOT EXISTS $1 (id INT)")
)
def test_positional_parameter_after_existence_clause_is_unread(dialect, sql):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts(sql)
    assert facts.objects == ()
    assert facts.opaque and facts.diagnostic
