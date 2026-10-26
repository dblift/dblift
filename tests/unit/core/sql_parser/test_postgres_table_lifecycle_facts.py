"""PostgreSQL table lifecycle facts needed by schema consumers."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import DeclaredConstraint, NamedObject


def _pg(sql):
    return read_statement_facts(sql, dialect="postgres")  # lint: allow-dialect-string: test


def test_table_rename_exposes_new_identity():
    facts = _pg("ALTER TABLE child RENAME TO old_child")

    assert facts.renamed_to == NamedObject("old_child", SqlObjectType.TABLE, "created")


def test_schema_qualified_table_rename_keeps_the_table_schema():
    facts = _pg('ALTER TABLE IF EXISTS "Sales"."Child" RENAME TO "OldChild";')

    assert facts.renamed_to == NamedObject("OldChild", SqlObjectType.TABLE, "created", "Sales")
    assert facts.renamed_to.name_quoted is True
    assert facts.renamed_to.schema_quoted is True


def test_alter_table_add_primary_key_exposes_declared_constraint():
    facts = _pg("ALTER TABLE t ADD CONSTRAINT pk_t PRIMARY KEY(id)")

    assert facts.declared_constraints == (DeclaredConstraint("PRIMARY_KEY", ("id",), "pk_t"),)


def test_qualified_table_and_quoted_primary_key_names_are_read():
    facts = _pg('ALTER TABLE "Sales"."Child" ADD CONSTRAINT "PkChild" PRIMARY KEY("Id", "Code");')

    assert facts.declared_constraints == (
        DeclaredConstraint("PRIMARY_KEY", ("Id", "Code"), "PkChild"),
    )


def test_unread_table_rename_tail_does_not_claim_a_destination():
    facts = _pg("ALTER TABLE child RENAME TO old_child bogus")

    assert facts.opaque
    assert facts.renamed_to is None


def test_table_rename_requires_a_single_unqualified_new_name():
    for sql in (
        "ALTER TABLE child RENAME TO s.old_child",
        "ALTER TABLE child RENAME TO old_child, ADD COLUMN x int",
    ):
        assert _pg(sql).renamed_to is None


def test_invalid_not_valid_primary_key_does_not_claim_a_constraint():
    facts = _pg("ALTER TABLE t ADD CONSTRAINT pk_t PRIMARY KEY(id) NOT VALID")

    assert facts.declared_constraints == ()


@pytest.mark.parametrize(
    "sql",
    ("ALTER TABLE t RENAME TO x NOT VALID", "ALTER TABLE t RENAME TO x,"),
)
def test_invalid_rename_tails_do_not_claim_a_destination(sql):
    facts = _pg(sql)

    assert facts.renamed_to is None
    assert facts.opaque


@pytest.mark.parametrize(
    "sql",
    (
        "ALTER TABLE t ADD CONSTRAINT p PRIMARY KEY(id,)",
        "ALTER TABLE t ADD CONSTRAINT p PRIMARY KEY(id) ON foo",
    ),
)
def test_invalid_primary_key_tails_do_not_claim_a_constraint(sql):
    facts = _pg(sql)

    assert facts.declared_constraints == ()
    assert facts.opaque


def test_inherited_table_definition_does_not_claim_a_primary_key():
    for sql in (
        "CREATE TABLE child (LIKE parent INCLUDING ALL)",
        "CREATE TABLE child PARTITION OF parent FOR VALUES IN (1)",
    ):
        facts = _pg(sql)

        assert NamedObject("parent", SqlObjectType.TABLE, "referenced") in facts.objects
        assert facts.declared_constraints == ()
