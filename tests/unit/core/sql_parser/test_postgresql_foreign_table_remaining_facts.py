"""Valid PostgreSQL foreign-table forms still outside the bounded facts grammar."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.statement_facts import NamedObject
from dblift.db.provider_registry import ProviderRegistry


@pytest.mark.parametrize(
    ("sql", "parent"),
    [
        ("CREATE FOREIGN TABLE ft PARTITION OF parent DEFAULT SERVER srv", "parent"),
        (
            "CREATE FOREIGN TABLE s.ft PARTITION OF s.parent FOR VALUES IN (1) SERVER srv",
            "s.parent",
        ),
        (
            "CREATE FOREIGN TABLE ft PARTITION OF parent FOR VALUES FROM (1) TO (10) SERVER srv",
            "parent",
        ),
        (
            "CREATE FOREIGN TABLE ft PARTITION OF parent FOR VALUES WITH (MODULUS 4, REMAINDER 1) SERVER srv",
            "parent",
        ),
    ],
)
def test_foreign_table_partition_of_reads_created_and_parent(sql, parent):
    facts = ProviderRegistry.get_quirks("postgresql").statement_facts(sql)

    created = NamedObject("ft", SqlObjectType.TABLE, "created", "s" if "s.ft" in sql else None)
    referenced = NamedObject(
        "parent", SqlObjectType.TABLE, "referenced", "s" if parent == "s.parent" else None
    )
    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert facts.objects == (created, referenced)
    assert not facts.opaque


@pytest.mark.parametrize(
    "sql",
    [
        "ALTER FOREIGN TABLE s.ft SET SCHEMA dest",
        "ALTER FOREIGN TABLE ft OWNER TO CURRENT_USER",
        "ALTER FOREIGN TABLE ft ENABLE TRIGGER t",
        "ALTER FOREIGN TABLE ft DISABLE TRIGGER ALL",
        "ALTER FOREIGN TABLE ft ALTER COLUMN c SET STORAGE PLAIN",
        "ALTER FOREIGN TABLE ft ADD COLUMN c integer, OPTIONS (ADD schema_name 'remote')",
    ],
)
def test_foreign_table_remaining_alter_actions_read_target(sql):
    facts = ProviderRegistry.get_quirks("postgresql").statement_facts(sql)

    expected = NamedObject("ft", SqlObjectType.TABLE, "altered", "s" if "s.ft" in sql else None)
    assert (facts.operation, facts.kind) == ("ALTER", "DDL")
    assert facts.objects == (expected,)
    assert not facts.opaque


@pytest.mark.parametrize("action", ["INHERIT", "NO INHERIT"])
def test_foreign_table_inheritance_action_reads_parent(action):
    facts = ProviderRegistry.get_quirks("postgresql").statement_facts(
        f"ALTER FOREIGN TABLE ft {action} s.parent"
    )

    assert (facts.operation, facts.kind) == ("ALTER", "DDL")
    assert facts.objects == (
        NamedObject("ft", SqlObjectType.TABLE, "altered"),
        NamedObject("parent", SqlObjectType.TABLE, "referenced", "s"),
    )
    assert not facts.opaque


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE FOREIGN TABLE ft PARTITION OF parent DEFAULT SERVER",
        "CREATE FOREIGN TABLE ft PARTITION OF parent FOR VALUES IN () SERVER srv",
        "CREATE FOREIGN TABLE ft PARTITION OF parent FOR VALUES IN (1,) SERVER srv",
        "CREATE FOREIGN TABLE ft PARTITION OF parent FOR VALUES IN (1,,2) SERVER srv",
        "CREATE FOREIGN TABLE ft PARTITION OF parent FOR VALUES FROM (1,) TO (2) SERVER srv",
        "CREATE FOREIGN TABLE ft PARTITION OF parent FOR VALUES FROM (1) (10) SERVER srv",
        "CREATE FOREIGN TABLE ft PARTITION OF parent FOR VALUES WITH (MODULUS 4 REMAINDER 1) SERVER srv",
        "CREATE FOREIGN TABLE ft PARTITION OF parent FOR VALUES WITH (MODULUS 0, REMAINDER 1) SERVER srv",
        "CREATE FOREIGN TABLE ft PARTITION OF parent FOR VALUES WITH (MODULUS 4, REMAINDER 4) SERVER srv",
        "CREATE FOREIGN TABLE ft PARTITION OF parent DEFAULT SERVER srv trailing",
        "CREATE FOREIGN TABLE s..ft PARTITION OF parent DEFAULT SERVER srv",
        "CREATE FOREIGN TABLE ft PARTITION OF s..parent DEFAULT SERVER srv",
        "ALTER FOREIGN TABLE ft SET SCHEMA",
        "ALTER FOREIGN TABLE ft OWNER TO",
        "ALTER FOREIGN TABLE s..ft OWNER TO owner1",
        "ALTER FOREIGN TABLE ft INHERIT s..parent",
        "ALTER FOREIGN TABLE ft ALTER COLUMN c SET STORAGE",
        "ALTER FOREIGN TABLE ft ADD COLUMN c integer, OPTIONS (ADD schema_name)",
    ],
)
def test_unread_foreign_table_tail_keeps_all_objects_opaque(sql):
    facts = ProviderRegistry.get_quirks("postgresql").statement_facts(sql)

    assert facts.opaque
    assert facts.objects == ()
