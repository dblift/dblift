"""Dialect-checked ADD COLUMN prefixes and named attributes in mixed ALTER statements."""

import pytest

from dblift.core.sql_parser.statement_facts import DeclaredConstraint
from dblift.db.provider_registry import ProviderRegistry


def _read(dialect, column):
    sql = f"ALTER TABLE t ADD UNIQUE(a), ADD COLUMN {column}"
    return ProviderRegistry.get_quirks(dialect).statement_facts_reader().read(sql)


@pytest.mark.parametrize(
    "dialect,column",
    [
        ("mysql", "IF NOT EXISTS b INT"),
        ("mysql", "b INT CONSTRAINT c AUTO_INCREMENT"),
        ("mariadb", "b INT CONSTRAINT c AUTO_INCREMENT"),
        ("mysql", "b INT CONSTRAINT c COMMENT 'test'"),
        ("mysql", "b INT CONSTRAINT c DEFAULT 1"),
        ("mysql", "b INT CONSTRAINT c NOT NULL"),
        ("postgresql", 'b INT CONSTRAINT c COLLATE "C"'),
    ],
)
def test_unproved_prefix_or_named_attribute_is_opaque(dialect, column):
    facts = _read(dialect, column)
    assert facts.opaque
    assert facts.declared_columns == ()
    assert facts.declared_constraints == ()


@pytest.mark.parametrize(
    "dialect,column",
    [
        ("postgresql", "IF NOT EXISTS b INT"),
        ("mariadb", "IF NOT EXISTS b INT"),
        ("postgresql", "b INT CONSTRAINT c DEFAULT 1"),
        ("postgresql", "b INT CONSTRAINT c NOT NULL"),
    ],
)
def test_supported_prefix_and_named_attributes_retain_keys(dialect, column):
    facts = _read(dialect, column)
    assert not facts.opaque
    assert facts.declared_columns == ("b",)
    assert facts.declared_constraints == (DeclaredConstraint("UNIQUE", ("a",)),)


@pytest.mark.parametrize("dialect", ["postgresql", "mysql", "mariadb"])
def test_named_column_check_keeps_its_name(dialect):
    facts = _read(dialect, "b INT CONSTRAINT positive CHECK (b > 0)")
    assert not facts.opaque
    assert facts.declared_constraints == (
        DeclaredConstraint("UNIQUE", ("a",)),
        DeclaredConstraint("CHECK", ("b",), "positive"),
    )
