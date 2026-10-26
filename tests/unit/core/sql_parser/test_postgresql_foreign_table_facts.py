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


@pytest.mark.parametrize(
    ("sql", "operation", "names"),
    [
        (
            "CREATE FOREIGN TABLE ft (id integer) SERVER srv OPTIONS (schema_name 'remote')",
            "CREATE",
            ("ft",),
        ),
        (
            "CREATE FOREIGN TABLE ft (id integer OPTIONS (column_name 'remote_id')) SERVER srv",
            "CREATE",
            ("ft",),
        ),
        (
            "CREATE FOREIGN TABLE ft (id integer) INHERITS (parent) SERVER srv",
            "CREATE",
            ("ft", "parent"),
        ),
        (
            "ALTER FOREIGN TABLE ft OPTIONS (ADD schema_name 'remote', DROP table_name)",
            "ALTER",
            ("ft",),
        ),
        (
            "ALTER FOREIGN TABLE ft ALTER COLUMN id OPTIONS (SET column_name 'remote_id')",
            "ALTER",
            ("ft",),
        ),
        ("DROP FOREIGN TABLE ft, other_ft CASCADE", "DROP", ("ft", "other_ft")),
    ],
)
def test_foreign_table_supported_options_and_targets_are_read(sql, operation, names):
    facts = ProviderRegistry.get_quirks("postgresql").statement_facts(sql)

    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert tuple(obj.name for obj in facts.objects) == names
    assert all(obj.type == SqlObjectType.TABLE for obj in facts.objects)
    assert not facts.opaque


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE FOREIGN TABLE ft (id integer) SERVER srv OPTIONS (schema_name)",
        "CREATE FOREIGN TABLE ft (id integer) OPTIONS (schema_name 'remote')",
        "ALTER FOREIGN TABLE ft OPTIONS (ADD schema_name)",
        "ALTER FOREIGN TABLE ft OPTIONS (DROP schema_name 'extra')",
        "ALTER FOREIGN TABLE ft ALTER COLUMN id OPTIONS (SET column_name)",
        "ALTER FOREIGN TABLE ft* DROP COLUMN id",
        "DROP FOREIGN TABLE ft, bad* CASCADE",
        "CREATE FOREIGN TABLE ft PARTITION OF parent DEFAULT SERVER srv",
        "CREATE FOREIGN TABLE ft (id integer OPTIONS (column_name)) SERVER srv",
        "CREATE FOREIGN TABLE ft (id integer UNIQUE) SERVER srv",
        "CREATE FOREIGN TABLE ft (id integer, PRIMARY KEY (id)) SERVER srv",
        "ALTER FOREIGN TABLE ft ADD CONSTRAINT u UNIQUE (id)",
        "ALTER FOREIGN TABLE ft RENAME TO new_ft .garbage",
        "ALTER FOREIGN TABLE ft RENAME COLUMN c TO d .garbage",
        "ALTER FOREIGN TABLE ft DROP COLUMN c .garbage",
        "ALTER FOREIGN TABLE ft ALTER COLUMN c TYPE text USING 1",
    ],
)
def test_foreign_table_unread_or_malformed_tail_stays_opaque(sql):
    facts = ProviderRegistry.get_quirks("postgresql").statement_facts(sql)

    assert facts.opaque
    assert facts.objects == ()


def test_postgresql_foreign_table_grammar_does_not_extend_to_wire_derivatives():
    facts = ProviderRegistry.get_quirks("cockroachdb").statement_facts("DROP FOREIGN TABLE ft")

    assert facts.opaque and facts.objects == ()
