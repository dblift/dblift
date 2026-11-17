"""Source-bound column collations in a mixed ALTER with a table key."""

import pytest

from dblift.core.sql_parser.statement_facts import DeclaredConstraint
from dblift.db.provider_registry import ProviderRegistry


def _read(dialect, collation):
    sql = f"ALTER TABLE t ADD UNIQUE(a), ADD COLUMN b VARCHAR(20) COLLATE {collation}"
    return ProviderRegistry.get_quirks(dialect).statement_facts_reader().read(sql)


@pytest.mark.parametrize(
    "dialect,collation",
    [
        ("postgresql", "ucs_basic"),
        ("postgresql", 'pg_catalog."C"'),
        ("postgresql", "pg_catalog.ucs_basic"),
        ("postgresql", '"C"'),
        ("mysql", "utf8mb4_bin"),
        ("mysql", "`utf8mb4_bin`"),
        ("mariadb", "utf8mb4_bin"),
        ("mariadb", "`utf8mb4_bin`"),
    ],
)
def test_column_collation_preserves_column_and_table_key(dialect, collation):
    facts = _read(dialect, collation)
    assert (facts.declared_columns, facts.declared_constraints) == (
        ("b",),
        (DeclaredConstraint("UNIQUE", ("a",)),),
    )
    assert not facts.opaque


@pytest.mark.parametrize(
    "dialect,collation",
    [
        ("postgresql", 'db.pg_catalog."C"'),
        ("postgresql", 'pg_catalog.""'),
        ("postgresql", '""'),
        ("postgresql", "pg_catalog..ucs_basic"),
        ("postgresql", "lower(ucs_basic)"),
        ("postgresql", "'ucs_basic'"),
        ("postgresql", "ucs_basic extra"),
        ("mysql", "db.utf8mb4_bin"),
        ("mysql", "SIGNAL"),
        ("mariadb", "db.utf8mb4_bin"),
        ("mariadb", "PAGE_CHECKSUM"),
        ("redshift", "utf8mb4_bin"),
    ],
)
def test_unproved_column_collation_keeps_mixed_alter_opaque(dialect, collation):
    facts = _read(dialect, collation)
    assert facts.opaque
    assert facts.declared_columns == ()
    assert facts.declared_constraints == ()
