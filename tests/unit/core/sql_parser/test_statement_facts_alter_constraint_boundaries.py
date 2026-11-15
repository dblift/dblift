"""A partially represented ALTER must not supply a plain key to its consumers."""

import pytest

from dblift.core.sql_parser.statement_facts import DeclaredConstraint
from dblift.db.provider_registry import ProviderRegistry


def _read(dialect, tail):
    return (
        ProviderRegistry.get_quirks(dialect).statement_facts_reader().read("ALTER TABLE t " + tail)
    )


@pytest.mark.parametrize(
    "dialect,tail",
    [
        ("postgresql", "ADD UNIQUE (a), DROP COLUMN b"),
        ("postgresql", "ADD UNIQUE (a), ADD FOREIGN KEY (b) REFERENCES p (x) NOT VALID"),
        ("postgresql", "ADD FOREIGN KEY (a, b) REFERENCES p (x)"),
        ("mysql", "ADD FOREIGN KEY (a) REFERENCES p"),
        ("mysql", "ADD UNIQUE (a(10))"),
        ("sqlserver", "ADD PRIMARY KEY (a DESC)"),
        ("sqlite", "ADD PRIMARY KEY (a)"),
        ("db2", "ADD UNIQUE (a) /*"),
        ("db2", "ADD UNIQUE (a) /* outer /* inner */"),
        ("postgresql", 'ADD CONSTRAINT "" UNIQUE (a)'),
        ("db2", "ADD UNIQUE (a) NOT ENFORCED"),
        ("db2", "ADD UNIQUE (a + 1)"),
        ("db2", "ADD FOREIGN KEY (a,b) REFERENCES p (x)"),
    ],
)
def test_unread_key_details_never_describe_a_complete_plain_key(dialect, tail):
    facts = _read(dialect, tail)
    assert facts.opaque
    assert facts.declared_constraints == ()


def test_native_db2_reports_a_fully_read_constraint_without_an_unavailable_diagnostic():
    facts = _read("db2", "ADD CONSTRAINT uq UNIQUE (a)")
    assert not facts.opaque
    assert facts.declared_constraints == (DeclaredConstraint("UNIQUE", ("A",), "UQ"),)


def test_mixed_add_actions_keep_declaration_order():
    facts = _read("postgresql", "ADD UNIQUE (a), ADD COLUMN b int PRIMARY KEY")
    assert not facts.opaque
    assert facts.declared_constraints == (
        DeclaredConstraint("UNIQUE", ("a",)),
        DeclaredConstraint("PRIMARY_KEY", ("b",)),
    )


@pytest.mark.parametrize(
    "dialect", ["postgresql", "sqlserver", "snowflake", "redshift", "oracle", "db2"]
)
def test_implicit_parent_key_does_not_invent_referenced_columns(dialect):
    facts = _read(dialect, "ADD FOREIGN KEY (a) REFERENCES p")
    column = "A" if dialect == "db2" else "a"
    table = "P" if dialect in {"db2", "snowflake", "oracle"} else "p"
    expected = (DeclaredConstraint("FOREIGN_KEY", (column,), referenced_table=table),)
    assert not facts.opaque
    assert facts.declared_constraints == expected
    assert [ref.name for ref in facts.objects if ref.role == "referenced"] == [table]
    if dialect == "postgresql":
        create = (
            ProviderRegistry.get_quirks(dialect)
            .statement_facts_reader()
            .read("CREATE TABLE t (a INT, FOREIGN KEY (a) REFERENCES p)")
        )
        assert create.declared_constraints == expected


def test_db2_consecutive_adds_are_all_read():
    facts = _read("db2", "ADD PRIMARY KEY (a) ADD FOREIGN KEY (b) REFERENCES p")
    assert not facts.opaque
    assert facts.declared_constraints == (
        DeclaredConstraint("PRIMARY_KEY", ("A",)),
        DeclaredConstraint("FOREIGN_KEY", ("B",), referenced_table="P"),
    )


def test_postgres_mixed_add_accepts_omitted_column_keyword():
    facts = _read("postgresql", "ADD a integer UNIQUE, ADD PRIMARY KEY (b)")
    assert not facts.opaque
    assert facts.declared_columns == ("a",)
    assert facts.declared_constraints == (
        DeclaredConstraint("UNIQUE", ("a",)),
        DeclaredConstraint("PRIMARY_KEY", ("b",)),
    )


def test_postgres_name_column_is_a_plain_key_identifier():
    facts = _read("postgresql", "ADD UNIQUE (name)")
    assert facts.declared_constraints == (DeclaredConstraint("UNIQUE", ("name",)),)
    assert not facts.opaque


def test_mysql_fk_index_name_does_not_replace_constraint_name():
    facts = _read("mysql", "ADD CONSTRAINT fk FOREIGN KEY idx (a) REFERENCES p (x)")
    assert not facts.opaque
    assert facts.declared_constraints == (
        DeclaredConstraint("FOREIGN_KEY", ("a",), "fk", "p", ("x",)),
    )
