"""``statement_dml_table`` names the table a DML statement targets, never its alias.

The result is interpolated into raw SQL (a capture ``SELECT ... FROM <target>``), so
``orders o`` or ``orders AS o`` is not a table reference a consumer can parse or reuse.
"""

import pytest

from dblift.db.dml_analysis import statement_dml_table
from dblift.db.provider_registry import ProviderRegistry

# Table alias written without AS: valid in every dialect below.
ALIASED = [
    ("UPDATE orders o SET x = 1 WHERE o.id = 1", "orders"),
    ("DELETE FROM orders o WHERE o.id = 1", "orders"),
    ("UPDATE app.orders o SET x = 1 WHERE o.id = 1", "app.orders"),
]
# ``AS`` before a table alias is a syntax error in Oracle.
ALIASED_WITH_AS = [
    ("UPDATE orders AS o SET x = 1 WHERE o.id = 1", "orders"),
    ("DELETE FROM orders AS o WHERE o.id = 1", "orders"),
]
DIALECTS = [
    "postgresql",
    "mysql",
    "mariadb",
    "sqlite",
    "duckdb",
    "oracle",
    "db2",
    "snowflake",
    "redshift",
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "expected"), ALIASED)
def test_an_aliased_target_is_the_bare_table(dialect, sql, expected):
    assert statement_dml_table(sql, quirks=ProviderRegistry.get_quirks(dialect)) == expected


@pytest.mark.parametrize("dialect", [d for d in DIALECTS if d != "oracle"])
@pytest.mark.parametrize(("sql", "expected"), ALIASED_WITH_AS)
def test_an_as_aliased_target_is_the_bare_table(dialect, sql, expected):
    assert statement_dml_table(sql, quirks=ProviderRegistry.get_quirks(dialect)) == expected


@pytest.mark.parametrize("dialect", ["oracle", "db2", "sqlite"])
def test_a_quoted_target_keeps_its_quoting_without_the_alias(dialect):
    quirks = ProviderRegistry.get_quirks(dialect)

    assert statement_dml_table('UPDATE "Orders" o SET x = 1', quirks=quirks) == '"Orders"'
