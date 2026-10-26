"""Statement facts retain identifier quoting without changing displayed names."""

import pytest

from dblift.db.provider_registry import ProviderRegistry

pytestmark = pytest.mark.unit


def _object(sql, role, object_type):
    facts = ProviderRegistry.get_quirks("postgresql").statement_facts(sql)
    return next(obj for obj in facts.objects if obj.role == role and obj.type.value == object_type)


def test_quoted_and_unquoted_postgresql_tables_keep_distinct_identity():
    plain = _object("CREATE TABLE Child(id int)", "created", "TABLE")
    quoted = _object('CREATE TABLE "Child"(id int)', "created", "TABLE")

    assert plain.name == quoted.name == "Child"
    assert plain.name_quoted is False
    assert quoted.name_quoted is True


def test_postgresql_schema_quoting_is_recorded_separately():
    plain = _object("CREATE TABLE App.child(id int)", "created", "TABLE")
    quoted = _object('CREATE TABLE "App".child(id int)', "created", "TABLE")

    assert plain.schema == quoted.schema == "App"
    assert plain.schema_quoted is False
    assert quoted.schema_quoted is True


def test_postgresql_index_owner_and_drop_keep_quote_provenance():
    owner = _object('CREATE INDEX ix ON "Child"(id)', "referenced", "TABLE")
    dropped = _object('DROP TABLE "Child"', "dropped", "TABLE")
    altered = _object('ALTER TABLE "Child" ADD COLUMN note text', "altered", "TABLE")
    index = _object('CREATE INDEX "Ix" ON child(id)', "created", "INDEX")

    assert owner.name == dropped.name == altered.name == "Child"
    assert owner.name_quoted is dropped.name_quoted is altered.name_quoted is True
    assert index.name == "Ix"
    assert index.name_quoted is True
