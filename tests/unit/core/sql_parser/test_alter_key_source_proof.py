"""Registered readers prove source spelling and dialect syntax before declaring keys."""

import pytest

from dblift.core.sql_parser.statement_facts import DeclaredConstraint
from dblift.db.provider_registry import ProviderRegistry


def _read(dialect, sql):
    return ProviderRegistry.get_quirks(dialect).statement_facts_reader().read(sql)


def _assert_unread(dialect, sql):
    facts = _read(dialect, sql)
    assert facts.opaque
    assert facts.declared_constraints == ()
    assert not any(obj.role == "referenced" for obj in facts.objects)


@pytest.mark.parametrize(
    "key",
    [
        "UNIQUE (a\u00a0)",
        "FOREIGN KEY (a) REFERENCES p\u00a0(x)",
        "FOREIGN KEY (a) REFERENCES s\u00a0.p(x)",
        "FOREIGN KEY (a) REFERENCES s.\u00a0p(x)",
        "FOREIGN KEY (a) REFERENCES s.p(x\u00a0)",
        "CONSTRAINT uq\u00a0 UNIQUE (a)",
        "UNIQUE (a \u00a0 )",
    ],
)
def test_db2_unread_tail_character_cannot_truncate_a_key_name(key):
    _assert_unread("db2", "ALTER TABLE t ADD " + key)


def test_db2_delimited_unicode_in_all_added_key_names():
    facts = _read(
        "db2",
        'ALTER TABLE t ADD CONSTRAINT "Né" FOREIGN KEY ("A\u00a0") REFERENCES "É"."P\u00a0" ("Xé")',
    )
    assert not facts.opaque
    assert facts.declared_constraints == (
        DeclaredConstraint("FOREIGN_KEY", ("A\u00a0",), "Né", "P\u00a0", ("Xé",)),
    )
    (ref,) = (o for o in facts.objects if o.role == "referenced")
    assert (ref.schema, ref.name, ref.name_quoted, ref.schema_quoted) == (
        "É",
        "P\u00a0",
        True,
        True,
    )


@pytest.mark.parametrize(
    "detail",
    [
        "REFERENCES p(x) ON DELETE CASCADE",
        "REFERENCES p(x,y)",
        "UNIQUE NULLS NOT DISTINCT",
        "UNIQUE DEFERRABLE",
        "PRIMARY KEY DEFERRABLE",
    ],
)
def test_mixed_inline_key_cannot_silently_discard_properties(detail):
    _assert_unread("postgresql", "ALTER TABLE t ADD UNIQUE(a), ADD COLUMN b int " + detail)


@pytest.mark.parametrize(
    "syntax",
    [
        "CREATE TABLE t (b int {})",
        "ALTER TABLE t ADD b int {}",
        "ALTER TABLE t ADD UNIQUE(a), ADD COLUMN b int {}",
    ],
)
@pytest.mark.parametrize(
    "detail,expected",
    [
        ('CONSTRAINT "Uq b" UNIQUE', DeclaredConstraint("UNIQUE", ("b",), "Uq b")),
        ("CONSTRAINT pk PRIMARY KEY", DeclaredConstraint("PRIMARY_KEY", ("b",), "pk")),
        (
            "CONSTRAINT fk REFERENCES p(x)",
            DeclaredConstraint("FOREIGN_KEY", ("b",), "fk", "p", ("x",)),
        ),
    ],
)
def test_inline_key_name_survives_every_column_projection(syntax, detail, expected):
    facts = _read("postgresql", syntax.format(detail))
    assert not facts.opaque
    assert facts.declared_constraints[-1] == expected


@pytest.mark.parametrize("name", ["date", "type", "timestamp"])
def test_nonreserved_postgres_keyword_in_key_name_positions(name):
    facts = _read(
        "postgresql",
        f"ALTER TABLE t ADD CONSTRAINT {name} FOREIGN KEY ({name}) REFERENCES p ({name})",
    )
    assert facts.declared_constraints == (
        DeclaredConstraint("FOREIGN_KEY", (name,), name, "p", (name,)),
    )
    assert not facts.opaque


@pytest.mark.parametrize("name", ["FROM", "CHECK", "TABLE", "ORDER", "SYSTEM_USER"])
def test_reserved_postgres_column_token_cannot_be_a_plain_key(name):
    _assert_unread("postgresql", f"ALTER TABLE t ADD UNIQUE ({name})")


@pytest.mark.parametrize(
    "dialect,prefix",
    [
        ("mysql", "IF EXISTS"),
        ("sqlserver", "IF EXISTS"),
        ("redshift", "IF EXISTS"),
        ("mysql", "ONLY"),
        ("mariadb", "ONLY"),
        ("sqlserver", "ONLY"),
        ("oracle", "ONLY"),
        ("snowflake", "ONLY"),
        ("redshift", "ONLY"),
    ],
)
def test_invalid_alter_prefix_yields_no_key(dialect, prefix):
    _assert_unread(dialect, f"ALTER TABLE {prefix} t ADD PRIMARY KEY (a)")


@pytest.mark.parametrize(
    "dialect,prefix",
    [
        ("postgresql", "IF EXISTS ONLY"),
        ("mariadb", "IF EXISTS"),
        ("duckdb", "IF EXISTS"),
        ("duckdb", "ONLY"),
        ("snowflake", "IF EXISTS"),
        ("oracle", "IF EXISTS"),
    ],
)
def test_dialect_supported_prefix_yields_key(dialect, prefix):
    facts = _read(dialect, f"ALTER TABLE {prefix} t ADD PRIMARY KEY (a)")
    assert not facts.opaque
    assert facts.declared_constraints == (DeclaredConstraint("PRIMARY_KEY", ("a",)),)


@pytest.mark.parametrize("dialect", ["mysql", "mariadb", "oracle"])
@pytest.mark.parametrize("table,parent", [("app.t", "cat.app.p"), ("cat.app.t", "app.p")])
def test_three_part_name_refused_where_table_qualification_ends_at_two(dialect, table, parent):
    _assert_unread(dialect, f"ALTER TABLE {table} ADD FOREIGN KEY(a) REFERENCES {parent}(x)")


@pytest.mark.parametrize("dialect", ["snowflake", "sqlserver"])
def test_qualified_subject_and_parent_keep_catalog_and_schema(dialect):
    facts = _read(
        dialect, 'ALTER TABLE "Db"."App"."Child" ADD FOREIGN KEY(a) REFERENCES "Db"."S"."Parent"(x)'
    )
    assert not facts.opaque
    altered, ref = facts.objects
    assert (altered.catalog, altered.schema, altered.name, altered.role) == (
        "Db",
        "Db.App",
        "Child",
        "altered",
    )
    assert (ref.catalog, ref.schema, ref.name, ref.role) == ("Db", "Db.S", "Parent", "referenced")
    assert facts.declared_constraints == (
        DeclaredConstraint(
            "FOREIGN_KEY", ("a",), referenced_table="Parent", referenced_columns=("x",)
        ),
    )


def test_sqlserver_explicit_cross_database_fk_is_opaque():
    _assert_unread("sqlserver", "ALTER TABLE db1.app.t ADD FOREIGN KEY(a) REFERENCES db2.app.p(x)")


def test_duckdb_fully_qualified_subject_supports_primary_key():
    facts = _read("duckdb", "ALTER TABLE memory.main.t ADD PRIMARY KEY(a)")
    assert facts.declared_constraints == (DeclaredConstraint("PRIMARY_KEY", ("a",)),)
