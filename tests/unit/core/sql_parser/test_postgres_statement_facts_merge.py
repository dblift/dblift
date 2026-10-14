"""PostgreSQL MERGE exposes only the explicit, modelled statement effects."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject, StatementFacts
from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks


@pytest.mark.parametrize(
    "branches,events,columns",
    [
        ("WHEN MATCHED THEN UPDATE SET value = s.value", {"UPDATE"}, ("value",)),
        ("WHEN MATCHED THEN DELETE", {"DELETE"}, ()),
        ("WHEN NOT MATCHED THEN INSERT (id, value) VALUES (s.id, s.value)", {"INSERT"}, ()),
        ("WHEN NOT MATCHED THEN INSERT VALUES (s.id, s.value)", {"INSERT"}, ()),
        ("WHEN NOT MATCHED THEN INSERT DEFAULT VALUES", {"INSERT"}, ()),
        ("WHEN MATCHED THEN DO NOTHING", set(), ()),
        ("WHEN NOT MATCHED THEN DO NOTHING", set(), ()),
        ("WHEN NOT MATCHED BY SOURCE THEN DELETE", {"DELETE"}, ()),
        (
            "WHEN MATCHED AND s.value < 0 THEN DELETE "
            "WHEN MATCHED AND s.value = 0 THEN DO NOTHING "
            "WHEN MATCHED THEN UPDATE SET value = s.value "
            "WHEN NOT MATCHED AND s.value > 0 THEN INSERT (id, value) VALUES (s.id, s.value)",
            {"INSERT", "UPDATE", "DELETE"},
            ("value",),
        ),
        (
            'WHEN MATCHED THEN UPDATE SET (value, "Other") = (s.value, DEFAULT)',
            {"UPDATE"},
            ("value", "Other"),
        ),
    ],
)
def test_postgres_merge_reports_declared_actions_without_promoting_conditions(
    branches, events, columns
):
    facts = read_statement_facts(
        "MERGE INTO public.items AS t USING staging.items AS s ON t.id = s.id " + branches,
        dialect="postgres",
    )

    assert facts == StatementFacts(
        "MERGE",
        "DML",
        (
            NamedObject("items", SqlObjectType.TABLE, "altered", "public"),
            NamedObject("items", SqlObjectType.TABLE, "referenced", "staging"),
        ),
        target="public.items",
        target_sql="public.items",
        affected_columns=columns,
        events=frozenset(events),
    )


@pytest.mark.parametrize(
    "target,name,schema,target_sql",
    [
        ('"Sales"."Order Items" AS t', "Order Items", "Sales", '"Sales"."Order Items"'),
        ('"a""b"."i""d" AS t', 'i"d', 'a"b', '"a""b"."i""d"'),
        ("ONLY items AS t", "items", None, "ONLY items"),
    ],
)
def test_postgres_merge_target_sql_removes_alias_but_preserves_identifier_and_only(
    target, name, schema, target_sql
):
    facts = read_statement_facts(
        f"MERGE INTO {target} USING source AS s ON t.id=s.id WHEN MATCHED THEN DELETE",
        dialect="postgres",
    )

    assert facts.affected_objects == (NamedObject(name, SqlObjectType.TABLE, "altered", schema),)
    assert facts.target == (f"{schema}.{name}" if schema else name)
    assert facts.target_sql == target_sql
    assert not facts.opaque


@pytest.mark.parametrize(
    "prefix,source,branches,references",
    [
        ("", "(SELECT * FROM raw.source) AS s", "WHEN MATCHED THEN DELETE", (("source", "raw"),)),
        (
            "WITH Source AS (SELECT * FROM raw.items) ",
            "SOURCE AS s",
            "WHEN MATCHED THEN DELETE",
            (("items", "raw"),),
        ),
        (
            'WITH "Source" AS (SELECT * FROM raw.items) ',
            '"Source" AS s',
            "WHEN MATCHED THEN DELETE",
            (("items", "raw"),),
        ),
        (
            'WITH "Source" AS (SELECT * FROM raw.items) ',
            "source AS s",
            "WHEN MATCHED THEN DELETE",
            (("items", "raw"), ("source", None)),
        ),
        (
            "WITH src AS (SELECT * FROM raw.items) ",
            "(WITH src AS (SELECT * FROM other.items) SELECT * FROM src) AS s",
            "WHEN MATCHED THEN DELETE",
            (("items", "raw"), ("items", "other")),
        ),
        ("", "items AS s", "WHEN MATCHED THEN DELETE", (("items", None),)),
        ("", "(VALUES (1, 2)) AS s(id, value)", "WHEN MATCHED THEN DELETE", ()),
        (
            "",
            "source AS s",
            "WHEN MATCHED AND EXISTS (SELECT 1 FROM flags) "
            "THEN UPDATE SET (value, other) = (SELECT value, other FROM lookup)",
            (("source", None), ("flags", None), ("lookup", None)),
        ),
        (
            "",
            "(SELECT a.* FROM source a JOIN source b ON a.id=b.id) s",
            "WHEN MATCHED THEN DELETE",
            (("source", None),),
        ),
    ],
)
def test_postgres_merge_resolves_physical_references_in_their_scopes(
    prefix, source, branches, references
):
    facts = read_statement_facts(
        f"{prefix}MERGE INTO items t USING {source} ON t.id=s.id {branches}",
        dialect="postgres",
    )

    assert facts.objects == (NamedObject("items", SqlObjectType.TABLE, "altered"),) + tuple(
        NamedObject(name, SqlObjectType.TABLE, "referenced", schema) for name, schema in references
    )
    assert not facts.opaque


@pytest.mark.parametrize(
    "sql",
    [
        "WITH src AS (DELETE FROM archived RETURNING *) "
        "MERGE INTO items t USING src s ON t.id=s.id WHEN MATCHED THEN DELETE",
        "MERGE INTO items t USING generate_series(1,2) s ON t.id=s.id WHEN MATCHED THEN DELETE",
        "MERGE INTO items t USING (SELECT * FROM generate_series(1,2)) s "
        "ON t.id=s.id WHEN MATCHED THEN DELETE",
        "MERGE INTO items t USING (SELECT * FROM unnest(ARRAY[1,2])) s "
        "ON t.id=s.id WHEN MATCHED THEN DELETE",
        "MERGE INTO items t USING source s ON t.id=s.id WHEN MATCHED THEN UPDATE SET value[1]=1",
        "MERGE INTO items t USING source s ON t.id=s.id WHEN MATCHED THEN UPDATE SET value.field=1",
        "MERGE INTO items t USING source s ON t.id=s.id WHEN MATCHED THEN UPDATE SET *",
        "MERGE INTO items t USING source s ON t.id=s.id WHEN MATCHED THEN UPDATE",
        "MERGE INTO items t USING source s ON t.id=s.id WHEN NOT MATCHED THEN INSERT *",
        "MERGE INTO items t USING source s ON t.id=s.id WHEN MATCHED THEN INSERT (id) VALUES(s.id)",
        "MERGE INTO items t USING source s ON t.id=s.id WHEN NOT MATCHED THEN DELETE",
    ],
)
def test_postgres_merge_unmodelled_effects_remain_opaque(sql):
    facts = read_statement_facts(sql, dialect="postgres")

    assert facts.operation == "MERGE"
    assert facts.opaque
    assert facts.objects == ()
    assert facts.target is None
    assert facts.target_sql is None
    assert facts.events is None
    assert facts.affected_columns == ()


def test_postgres_merge_does_not_activate_the_plugin():
    assert not PostgresqlQuirks().supports_statement_facts
