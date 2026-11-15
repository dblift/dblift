"""ALTER constraints use the registered reader and the existing declaration shape."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.statement_facts import DeclaredConstraint
from dblift.db.provider_registry import ProviderRegistry

# SQLite cannot ADD a table constraint. DuckDB's installed 1.x engine supports
# adding primary keys; only those forms are positive contracts here.
DIALECTS = [
    "postgresql",
    "mysql",
    "mariadb",
    "oracle",
    "sqlserver",
    "snowflake",
    "redshift",
    "db2",
]


def _read(dialect, sql):
    return ProviderRegistry.get_quirks(dialect).statement_facts_reader().read(sql)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "declaration,expected",
    [
        ("UNIQUE (a)", DeclaredConstraint("UNIQUE", ("a",))),
        ("PRIMARY KEY (a)", DeclaredConstraint("PRIMARY_KEY", ("a",))),
        (
            "FOREIGN KEY (a) REFERENCES parent (x)",
            DeclaredConstraint(
                "FOREIGN_KEY", ("a",), referenced_table="parent", referenced_columns=("x",)
            ),
        ),
        (
            "CONSTRAINT uq UNIQUE (a, b)",
            DeclaredConstraint("UNIQUE", ("a", "b"), "uq"),
        ),
        (
            "CONSTRAINT pk PRIMARY KEY (a, b)",
            DeclaredConstraint("PRIMARY_KEY", ("a", "b"), "pk"),
        ),
        (
            "CONSTRAINT fk FOREIGN KEY (a, b) REFERENCES parent (x, y)",
            DeclaredConstraint("FOREIGN_KEY", ("a", "b"), "fk", "parent", ("x", "y")),
        ),
    ],
    ids=[
        "bare-unique",
        "bare-pk",
        "bare-fk",
        "named-composite-unique",
        "named-composite-pk",
        "named-composite-fk",
    ],
)
def test_add_constraint_exposes_the_existing_declaration(dialect, declaration, expected):
    facts = _read(dialect, "ALTER TABLE child ADD " + declaration)
    if dialect == "db2":
        # Db2's native reader folds unquoted names, unlike SQLGlot readers.
        expected = DeclaredConstraint(
            expected.kind,
            tuple(column.upper() for column in expected.columns),
            expected.name.upper() if expected.name else None,
            expected.referenced_table.upper() if expected.referenced_table else None,
            tuple(column.upper() for column in expected.referenced_columns),
        )

    elif dialect in {"oracle", "snowflake"} and expected.referenced_table:
        # Table names fold; constraint and column names retain their written spelling.
        expected = DeclaredConstraint(
            expected.kind,
            expected.columns,
            expected.name,
            expected.referenced_table.upper(),
            expected.referenced_columns,
        )
    assert (facts.operation, facts.kind) == ("ALTER", "DDL")
    assert facts.error is None
    assert facts.declared_constraints == (expected,)
    assert facts.declared_columns == ()
    assert facts.affected_objects[0].name == (
        "CHILD" if dialect in {"db2", "oracle", "snowflake"} else "child"
    )


@pytest.mark.parametrize(
    "dialect",
    [
        "cockroachdb",
        "yugabytedb",
        "alloydb",
        "aurora-postgresql",
        "citus",
        "neon",
        "supabase",
        "timescaledb",
    ],
)
def test_postgresql_sibling_plugins_expose_added_foreign_key(dialect):
    facts = _read(dialect, "ALTER TABLE child ADD FOREIGN KEY (a) REFERENCES parent (id)")

    assert facts.declared_constraints == (
        DeclaredConstraint(
            "FOREIGN_KEY", ("a",), referenced_table="parent", referenced_columns=("id",)
        ),
    )
    assert facts.error is None


@pytest.mark.parametrize("prefix,name", [("", None), ("CONSTRAINT pk ", "pk")])
def test_duckdb_add_primary_key(prefix, name):
    facts = _read("duckdb", "ALTER TABLE child ADD " + prefix + "PRIMARY KEY (a, b)")

    assert facts.declared_constraints == (DeclaredConstraint("PRIMARY_KEY", ("a", "b"), name),)
    assert facts.error is None


@pytest.mark.parametrize("dialect,quote", [("postgresql", '"'), ("mysql", "`"), ("db2", '"')])
def test_quoted_added_foreign_key_preserves_the_existing_reference_identity(dialect, quote):
    def quoted(name):
        return quote + name + quote

    sql = (
        f"ALTER TABLE {quoted('App')}.{quoted('Child')} "
        f"ADD CONSTRAINT {quoted('Fk Name')} FOREIGN KEY ({quoted('Left')}, {quoted('Right')}) "
        f"REFERENCES {quoted('Remote')}.{quoted('Parent')} ({quoted('X')}, {quoted('Y')})"
    )
    facts = _read(dialect, sql)

    assert facts.declared_constraints == (
        DeclaredConstraint("FOREIGN_KEY", ("Left", "Right"), "Fk Name", "Parent", ("X", "Y")),
    )
    assert facts.error is None
    references = [obj for obj in facts.objects if obj.role == "referenced"]
    assert len(references) == 1
    reference = references[0]
    assert (reference.name, reference.schema, reference.type) == (
        "Parent",
        "Remote",
        SqlObjectType.TABLE,
    )
    assert (reference.name_quoted, reference.schema_quoted) == (True, True)
    altered = facts.affected_objects[0]
    assert (altered.name, altered.schema) == ("Child", "App")
    assert (altered.name_quoted, altered.schema_quoted) == (True, True)


@pytest.mark.parametrize(
    "sql,columns,expected",
    [
        (
            "ALTER TABLE child ADD CONSTRAINT uq UNIQUE (a), "
            "ADD CONSTRAINT fk FOREIGN KEY (b) REFERENCES parent (id)",
            (),
            (
                DeclaredConstraint("UNIQUE", ("a",), "uq"),
                DeclaredConstraint("FOREIGN_KEY", ("b",), "fk", "parent", ("id",)),
            ),
        ),
        (
            "ALTER TABLE child ADD COLUMN a int UNIQUE, ADD CONSTRAINT pk PRIMARY KEY (b)",
            ("a",),
            (DeclaredConstraint("UNIQUE", ("a",)), DeclaredConstraint("PRIMARY_KEY", ("b",), "pk")),
        ),
    ],
)
def test_postgresql_multiple_add_actions_keep_all_declarations(sql, columns, expected):
    facts = _read("postgresql", sql)

    assert facts.declared_columns == columns
    assert facts.declared_constraints == expected
    assert facts.error is None


def test_create_and_added_inline_column_constraints_are_existing_controls():
    created = _read(
        "postgresql",
        "CREATE TABLE child (a int PRIMARY KEY, b int UNIQUE, "
        'CONSTRAINT fk FOREIGN KEY (b) REFERENCES "Remote"."Parent" ("X"))',
    )
    assert created.declared_constraints == (
        DeclaredConstraint("PRIMARY_KEY", ("a",)),
        DeclaredConstraint("UNIQUE", ("b",)),
        DeclaredConstraint("FOREIGN_KEY", ("b",), "fk", "Parent", ("X",)),
    )
    reference = [obj for obj in created.objects if obj.role == "referenced"][0]
    assert (reference.name, reference.schema) == ("Parent", "Remote")
    assert (reference.name_quoted, reference.schema_quoted) == (True, True)
    added = _read("postgresql", "ALTER TABLE child ADD COLUMN a int UNIQUE")
    assert added.declared_columns == ("a",)
    assert added.declared_constraints == (DeclaredConstraint("UNIQUE", ("a",)),)


def test_named_postgresql_primary_key_is_an_existing_control():
    facts = _read(
        "postgresql", 'ALTER TABLE "App"."Child" ADD CONSTRAINT "Pk Name" PRIMARY KEY ("A", "B")'
    )

    assert facts.declared_constraints == (DeclaredConstraint("PRIMARY_KEY", ("A", "B"), "Pk Name"),)
    assert not facts.opaque


@pytest.mark.parametrize(
    "tail",
    [
        "ADD CONSTRAINT uq UNIQUE USING INDEX uq_idx",
        "ADD CONSTRAINT pk PRIMARY KEY USING INDEX pk_idx",
        "ADD CONSTRAINT pk PRIMARY KEY (a) DEFERRABLE INITIALLY DEFERRED",
        "ADD UNIQUE (a) GARBAGE",
        "ADD FOREIGN KEY (a) REFERENCES",
    ],
)
def test_unread_or_malformed_constraint_details_remain_conservative(tail):
    facts = _read("postgresql", "ALTER TABLE child " + tail)

    assert facts.opaque
    assert facts.declared_constraints == ()


def test_db2_unrelated_column_facts_remain_intentionally_unavailable():
    facts = _read("db2", "ALTER TABLE child ADD COLUMN a INT")

    assert facts.opaque
    assert facts.declared_columns == ()
    assert facts.declared_constraints == ()
