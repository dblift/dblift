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


@pytest.mark.parametrize(
    "sql, identity_field, expected",
    [
        ('SELECT * FROM Foo JOIN "Foo" ON true', "name_quoted", [False, True]),
        ('SELECT * FROM App.foo JOIN "App".foo ON true', "schema_quoted", [False, True]),
        (
            'MERGE INTO target AS t USING (SELECT a.id FROM Foo a JOIN "Foo" b '
            "ON a.id=b.id) s ON t.id=s.id WHEN MATCHED THEN UPDATE SET id=s.id",
            "name_quoted",
            [False, True],
        ),
    ],
)
def test_postgresql_references_keep_quote_distinct_sources(sql, identity_field, expected):
    facts = ProviderRegistry.get_quirks("postgresql").statement_facts(sql)
    references = [obj for obj in facts.objects if obj.role == "referenced"]

    assert [getattr(obj, identity_field) for obj in references] == expected


def test_duckdb_copy_query_keeps_quote_distinct_sources():
    facts = ProviderRegistry.get_quirks("duckdb").statement_facts(
        "COPY (SELECT * FROM Foo JOIN \"Foo\" ON true) TO 'x.csv'"
    )

    assert [obj.name_quoted for obj in facts.objects] == [False, True]


@pytest.mark.parametrize(
    "left, right, catalogs",
    [
        ('"memory.foo".t', "memory.foo.t", [None, "memory"]),
        ('a."b.c".t', '"a.b".c.t', ["a", "a.b"]),
    ],
)
def test_duckdb_flattened_schema_keeps_catalog_boundary(left, right, catalogs):
    quirks = ProviderRegistry.get_quirks("duckdb")
    objects = [
        quirks.statement_facts(f"CREATE TABLE {name}(id INT)").objects[0] for name in (left, right)
    ]

    assert objects[0].schema == objects[1].schema
    assert [getattr(obj, "catalog", None) for obj in objects] == catalogs


def test_duckdb_same_flattened_sources_remain_distinct():
    facts = ProviderRegistry.get_quirks("duckdb").statement_facts(
        'SELECT * FROM a."b.c".t JOIN "a.b".c.t ON true'
    )

    assert len(facts.objects) == 2
    assert [getattr(obj, "catalog", None) for obj in facts.objects] == ["a", "a.b"]


def test_postgresql_quoted_table_is_not_an_unquoted_cte_alias():
    facts = ProviderRegistry.get_quirks("postgresql").statement_facts(
        'WITH foo AS (SELECT 1) SELECT * FROM "Foo"'
    )

    assert [(obj.name, obj.name_quoted) for obj in facts.objects] == [("Foo", True)]


@pytest.mark.parametrize("verb, role", [("CREATE", "created"), ("DROP", "dropped")])
def test_postgresql_schema_identity_keeps_ast_quote_provenance(verb, role):
    plain = _object(f"{verb} SCHEMA App", role, "SCHEMA")
    quoted = _object(f'{verb} SCHEMA "App"', role, "SCHEMA")

    assert plain.name == quoted.name == "App"
    assert plain.name_quoted is False
    assert quoted.name_quoted is True


def test_postgresql_trigger_identity_keeps_ast_quote_provenance():
    trigger = _object(
        'CREATE TRIGGER "Tg" AFTER INSERT ON t FOR EACH ROW EXECUTE FUNCTION f()',
        "created",
        "TRIGGER",
    )

    assert trigger.name == "Tg"
    assert trigger.name_quoted is True
