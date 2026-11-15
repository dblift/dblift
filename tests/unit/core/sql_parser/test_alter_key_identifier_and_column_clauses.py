"""Source-bound PostgreSQL identifiers and mixed column declarations."""

import pytest

from dblift.core.sql_parser.statement_facts import DeclaredConstraint
from dblift.db.provider_registry import ProviderRegistry


def _read(sql):
    return ProviderRegistry.get_quirks("postgresql").statement_facts_reader().read(sql)


@pytest.mark.parametrize("name", ["old", "new", "of", "off", "between", "over", "order$number"])
def test_nonreserved_key_column_name(name):
    facts = _read(f"ALTER TABLE t ADD UNIQUE({name})")
    assert facts.declared_constraints == (DeclaredConstraint("UNIQUE", (name,)),)
    assert not facts.opaque


@pytest.mark.parametrize("source,target", [("t", "old"), ("old", "new")])
def test_nonreserved_rename_names(source, target):
    facts = _read(f"ALTER TABLE {source} RENAME TO {target}")
    assert facts.renamed_to is not None
    assert facts.renamed_to.name == target
    assert facts.objects[0].name == source
    assert not facts.opaque


@pytest.mark.parametrize("name", ["JOIN", "FULL", "ILIKE", "'old'"])
def test_non_column_identifier_in_table_key_is_opaque(name):
    facts = _read(f"ALTER TABLE t ADD UNIQUE({name})")
    assert facts.opaque
    assert not facts.declared_constraints


@pytest.mark.parametrize(
    "detail,extras",
    [
        ("CHECK (b>0)", (DeclaredConstraint("CHECK", ("b",)),)),
        ('CONSTRAINT "Pos" CHECK (b>0)', (DeclaredConstraint("CHECK", ("b",), "Pos"),)),
        ('COLLATE "C"', ()),
        ("NOT NULL DEFAULT 1", ()),
    ],
)
def test_modeled_column_clause_preserved_beside_table_key(detail, extras):
    facts = _read(f"ALTER TABLE t ADD UNIQUE(a), ADD COLUMN b INT {detail}")
    assert facts.declared_columns == ("b",)
    assert facts.declared_constraints == (DeclaredConstraint("UNIQUE", ("a",)), *extras)
    assert not facts.opaque


@pytest.mark.parametrize("name", ["FROM", "123", '""', "'old'"])
def test_invalid_mixed_column_name_keeps_the_statement_opaque(name):
    facts = _read(f"ALTER TABLE t ADD UNIQUE(a), ADD COLUMN {name} INT UNIQUE")
    assert facts.opaque
    assert facts.declared_columns == ()
    assert facts.declared_constraints == ()


@pytest.mark.parametrize("name", ["FROM", "123"])
def test_mixed_delimited_column_name(name):
    facts = _read(f'ALTER TABLE t ADD UNIQUE(a), ADD COLUMN "{name}" INT UNIQUE')
    assert not facts.opaque
    assert facts.declared_columns == (name,)
    assert facts.declared_constraints == (
        DeclaredConstraint("UNIQUE", ("a",)),
        DeclaredConstraint("UNIQUE", (name,)),
    )


def test_mixed_column_check_does_not_make_modified_key_complete():
    facts = _read("ALTER TABLE t ADD UNIQUE(a), ADD COLUMN b INT CHECK (b>0) UNIQUE DEFERRABLE")
    assert facts.opaque
    assert facts.declared_constraints == ()
