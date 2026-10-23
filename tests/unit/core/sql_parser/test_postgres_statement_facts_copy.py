"""PostgreSQL COPY facts read a table transfer and ignore the options.

``COPY t FROM`` loads ``t`` whatever follows the source (``FORMAT``, ``HEADER``, ``WITH (...)``,
``CSV``); ``COPY t TO`` reads it. The source is a literal file, ``STDIN``, ``STDOUT`` (either word in
either direction) or
``PROGRAM '...'``. A query source, a path the grammar leaves to an expression and the old
``COPY BINARY t`` spelling (which the grammar reads as a table named BINARY) stay unread.
"""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.statement_facts import (
    NamedObject,
    SqlglotStatementFactsReader,
    StatementFacts,
)
from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import PostgreSqlRegexParser
from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks


@pytest.mark.parametrize(
    "sql,name,schema,target_sql,columns",
    [
        ("COPY public.t FROM '/tmp/in.csv'", "t", "public", "public.t", ()),
        (
            'COPY "Sales"."Order Items" ("Item ID", price) FROM \'in.csv\'',
            "Order Items",
            "Sales",
            '"Sales"."Order Items"',
            ("Item ID", "price"),
        ),
        ("COPY t FROM 'STDIN'", "t", None, "t", ()),
        ("COPY t FROM 'STDOUT'", "t", None, "t", ()),
        ("/* import */ COPY t FROM /* path */ 'in.csv';", "t", None, "t", ()),
        ("COPY t FROM 'file' (FORMAT CSV, HEADER)", "t", None, "t", ()),
        ("COPY t FROM STDIN", "t", None, "t", ()),
        # the grammar reads STDOUT after FROM as the same client stream (PostgreSQL 16.14 loads it)
        ("COPY t FROM STDOUT", "t", None, "t", ()),
        ("COPY t FROM stdin;", "t", None, "t", ()),
        (
            "COPY public.t (a, b) FROM STDIN WITH (FORMAT csv, HEADER true)",
            "t",
            "public",
            "public.t",
            ("a", "b"),
        ),
        ("COPY t FROM STDIN CSV HEADER DELIMITER ','", "t", None, "t", ()),
        ("COPY t FROM 'in.csv' WITH (FORMAT CSV)", "t", None, "t", ()),
        ("COPY t FROM 'in.csv' CSV", "t", None, "t", ()),
        ("COPY t FROM PROGRAM 'echo 1'", "t", None, "t", ()),
        # the file is any string literal PostgreSQL 16.14 accepts
        ("COPY t FROM $$in.csv$$", "t", None, "t", ()),
        ("COPY t FROM E'in.csv'", "t", None, "t", ()),
        ("COPY t FROM U&'in.csv'", "t", None, "t", ()),
    ],
)
def test_postgres_copy_file_import_facts(sql, name, schema, target_sql, columns):
    facts = SqlglotStatementFactsReader("postgres").read(sql)

    assert facts == StatementFacts(
        "COPY",
        "DML",
        (NamedObject(name, SqlObjectType.TABLE, "altered", schema),),
        f"{schema}.{name}" if schema else name,
        affected_columns=columns,
        events=frozenset({"INSERT"}),
        target_sql=target_sql,
    )


@pytest.mark.parametrize(
    "sql,name,schema",
    [
        ("COPY public.t TO '/tmp/out.csv'", "t", "public"),
        ('COPY "Sales"."Order Items" ("Item ID") TO \'out.csv\'', "Order Items", "Sales"),
        ("COPY t TO 'STDOUT'", "t", None),
        ("COPY t TO 'STDIN'", "t", None),
        ("COPY t TO STDOUT", "t", None),
        ("COPY t TO STDIN", "t", None),
        ("COPY t (a) TO STDOUT WITH (FORMAT csv, HEADER)", "t", None),
        ("COPY t TO '/tmp/out.csv' CSV HEADER", "t", None),
        ("COPY t TO PROGRAM 'cat'", "t", None),
    ],
)
def test_postgres_copy_file_export_is_read_only(sql, name, schema):
    facts = SqlglotStatementFactsReader("postgres").read(sql)

    assert facts == StatementFacts(
        "COPY", "QUERY", (NamedObject(name, SqlObjectType.TABLE, "referenced", schema),)
    )
    assert facts.affected_objects == ()


@pytest.mark.parametrize(
    "sql",
    [
        "COPY (SELECT * FROM t) TO 'out.csv'",
        "COPY (SELECT * FROM t) TO STDOUT",
        "COPY (DELETE FROM t RETURNING *) TO 'out.csv'",
        "COPY (WITH a AS (SELECT * FROM t) SELECT * FROM a) TO 'out.csv'",
        "COPY (WITH a AS (DELETE FROM t RETURNING *) SELECT * FROM a) TO 'out.csv'",
        "COPY BINARY t FROM STDIN",
        'COPY t FROM "STDIN"',
        "COPY t FROM PROGRAM",
        "COPY t FROM 'in' || '.csv'",
        "COPY t FROM ('in' || '.csv')",
        "COPY t FROM 'a.csv', 'b.csv'",
        "COPY t FROM ?",
        "COPY t FROM $1",
        "COPY t 'in.csv'",
        "COPY t () FROM 'in.csv'",
        "COPY ONLY t FROM 'in.csv'",
        "COPY db.public.t FROM 'in.csv'",
        "COPY \"\" FROM 'in.csv'",
        "COPY \"\".t FROM 'in.csv'",
        "COPY t FROM 'in.csv'; DELETE FROM t",
        "COPY t FROM 'in.csv'; -- end",
        "COPY t WITH () FROM 'in.csv'",
        "COPY t FROM 'in.csv' WHERE id > 0",
        "COPY t FROM STDIN;\n1\n\\.\n",
    ],
)
def test_postgres_unsupported_copy_does_not_invent_effects(sql):
    facts = SqlglotStatementFactsReader("postgres").read(sql)

    assert facts.operation == "COPY"
    assert facts.kind == "UNKNOWN"
    assert facts.objects == ()
    assert facts.target is None
    assert facts.target_sql is None
    assert facts.predicate is None
    assert facts.events is None
    assert facts.affected_columns == ()
    assert facts.opaque


@pytest.mark.parametrize("dialect", ["sqlite", "mysql", "oracle", "tsql"])
def test_postgres_copy_facts_preserve_other_dialect_mappings(dialect):
    facts = SqlglotStatementFactsReader(dialect).read("COPY public.t FROM 'in.csv'")

    assert facts.operation == "COPY"
    assert facts.kind == "UNKNOWN"
    assert facts.objects == ()
    assert facts.opaque


def test_postgres_copy_facts_are_read_by_the_plugin():
    assert PostgresqlQuirks().supports_statement_facts


@pytest.mark.parametrize(
    "sql",
    [
        "WITH source AS (SELECT * FROM t) COPY t TO 'out.csv'",
        "WITH source AS (DELETE FROM t RETURNING *) COPY t TO 'out.csv'",
    ],
)
def test_copy_after_with_remains_opaque_without_guessed_effects(sql):
    facts = SqlglotStatementFactsReader("postgres").read(sql)

    assert facts.opaque
    assert facts.objects == ()
    assert facts.target is None
    assert facts.target_sql is None
    assert facts.events is None
    assert facts.affected_columns == ()


def test_copy_inline_payload_is_read_from_its_header():
    sql = "COPY t (a) FROM STDIN;\n1\n\\.\n"
    statements = PostgreSqlRegexParser().split_for_analysis(sql)
    assert len(statements) == 1
    facts = SqlglotStatementFactsReader("postgres").read(statements[0])

    assert facts == StatementFacts(
        "COPY",
        "DML",
        (NamedObject("t", SqlObjectType.TABLE, "altered"),),
        "t",
        affected_columns=("a",),
        events=frozenset({"INSERT"}),
        target_sql="t",
    )
