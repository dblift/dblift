"""PostgreSQL foreign-table DDL exposes proven table identities."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.statement_facts import NamedObject
from dblift.db.provider_registry import ProviderRegistry


@pytest.mark.parametrize(
    ("sql", "operation", "role"),
    [
        ("CREATE FOREIGN TABLE s.ft (id integer) SERVER srv", "CREATE", "created"),
        ("ALTER FOREIGN TABLE s.ft ADD COLUMN c integer", "ALTER", "altered"),
        ("DROP FOREIGN TABLE IF EXISTS s.ft CASCADE", "DROP", "dropped"),
        ('CREATE FOREIGN TABLE "S"."Mixed" (id integer) SERVER srv', "CREATE", "created"),
        ('ALTER FOREIGN TABLE "S"."Mixed" RENAME TO "New"', "ALTER", "altered"),
        ('DROP FOREIGN TABLE IF EXISTS "S"."Mixed"', "DROP", "dropped"),
    ],
)
def test_foreign_table_ddl_names_its_table(sql, operation, role):
    facts = ProviderRegistry.get_quirks("postgresql").statement_facts(sql)

    schema, name = ("S", "Mixed") if '"S"' in sql else ("s", "ft")
    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert facts.objects == (NamedObject(name, SqlObjectType.TABLE, role, schema),)
    assert not facts.opaque


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE FOREIGN TABLE s..ft (id integer) SERVER srv",
        "ALTER FOREIGN TABLE .ft ADD COLUMN c integer",
        "DROP FOREIGN TABLE s.ft*",
        "CREATE FOREIGN TABLE :name (id integer) SERVER srv",
    ],
)
def test_foreign_table_ddl_does_not_invent_a_name(sql):
    facts = ProviderRegistry.get_quirks("postgresql").statement_facts(sql)

    assert facts.objects == ()
    assert facts.opaque
