"""PostgreSQL statement facts name the object of COMMENT ON, triggers, schemas, SELECT INTO and
statements the grammar returns as opaque commands.

Every expectation is built by hand from what PostgreSQL runs. The other dialects keep the facts they
had: the negative tests pin them.
"""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject, StatementFacts

T = SqlObjectType


def _pg(sql):
    return read_statement_facts(sql, dialect="postgres")  # lint: allow-dialect-string: test


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("COMMENT ON TABLE t IS 'x'", NamedObject("t", T.TABLE, "altered")),
        ("COMMENT ON TABLE s.t IS 'x'", NamedObject("t", T.TABLE, "altered", "s")),
        ("COMMENT ON COLUMN t.c IS 'x'", NamedObject("t", T.TABLE, "altered")),
        ("COMMENT ON COLUMN s.t.c IS 'x'", NamedObject("t", T.TABLE, "altered", "s")),
        ("COMMENT ON INDEX i IS 'x'", NamedObject("i", T.INDEX, "altered")),
        ("COMMENT ON SEQUENCE q IS 'x'", NamedObject("q", T.SEQUENCE, "altered")),
        ("COMMENT ON VIEW v IS 'x'", NamedObject("v", T.VIEW, "altered")),
        (
            "COMMENT ON MATERIALIZED VIEW mv IS 'x'",
            NamedObject("mv", T.MATERIALIZED_VIEW, "altered"),
        ),
        ("COMMENT ON SCHEMA s IS 'x'", NamedObject("s", T.SCHEMA, "altered")),
    ],
)
def test_comment_on_names_the_object_it_changes(sql, expected):
    assert _pg(sql) == StatementFacts("COMMENT", "DDL", (expected,))


@pytest.mark.parametrize(
    "sql",
    [
        "COMMENT ON EXTENSION e IS 'x'",
        "COMMENT ON TRIGGER tg ON t IS 'x'",
        "COMMENT ON CONSTRAINT c ON t IS 'x'",
    ],
)
def test_comment_on_an_object_that_cannot_be_named_is_still_ddl(sql):
    facts = _pg(sql)

    assert (facts.operation, facts.kind, facts.objects) == ("COMMENT", "DDL", ())
    assert facts.opaque
    assert facts.error is None


@pytest.mark.parametrize("dialect", ["mysql", "tsql"])
def test_comment_on_is_unchanged_for_other_dialects(dialect):
    facts = read_statement_facts("COMMENT ON TABLE t IS 'x'", dialect=dialect)

    assert facts == StatementFacts(
        "COMMENT",
        "UNKNOWN",
        diagnostic=f"{dialect} Comment has no statement facts mapping",
    )


@pytest.mark.parametrize(
    "sql,trigger,schema",
    [
        ("CREATE TRIGGER tg AFTER INSERT ON s.t FOR EACH ROW EXECUTE FUNCTION f()", "tg", "s"),
        ('CREATE TRIGGER "Tg" AFTER INSERT ON s.t FOR EACH ROW EXECUTE FUNCTION f()', "Tg", "s"),
        (
            "CREATE OR REPLACE TRIGGER tg AFTER INSERT ON s.t FOR EACH ROW EXECUTE FUNCTION f()",
            "tg",
            "s",
        ),
        (
            "CREATE CONSTRAINT TRIGGER tg AFTER INSERT ON s.t FOR EACH ROW EXECUTE FUNCTION f()",
            "tg",
            "s",
        ),
        ("CREATE TRIGGER tg AFTER INSERT ON t FOR EACH ROW EXECUTE FUNCTION f()", "tg", None),
    ],
)
def test_create_trigger_names_the_trigger_then_its_table(sql, trigger, schema):
    assert _pg(sql) == StatementFacts(
        "CREATE",
        "DDL",
        (
            NamedObject(trigger, T.TRIGGER, "created"),
            NamedObject("t", T.TABLE, "referenced", schema),
        ),
    )


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("DROP SCHEMA s", NamedObject("s", T.SCHEMA, "dropped")),
        ("DROP SCHEMA IF EXISTS s CASCADE", NamedObject("s", T.SCHEMA, "dropped")),
        ('DROP SCHEMA "Sales" RESTRICT', NamedObject("Sales", T.SCHEMA, "dropped")),
        (
            'DROP SCHEMA "Warehouse"."Reporting"',
            NamedObject("Reporting", T.SCHEMA, "dropped", "Warehouse"),
        ),
    ],
)
def test_drop_schema_names_the_schema(sql, expected):
    assert _pg(sql) == StatementFacts("DROP", "DDL", (expected,))


def test_drop_of_two_schemas_stays_opaque_and_names_only_the_first():
    facts = _pg("DROP SCHEMA a, b")

    assert (facts.operation, facts.kind) == ("DROP", "DDL")
    assert facts.objects == (NamedObject("a", T.SCHEMA, "dropped"),)
    assert facts.opaque


@pytest.mark.parametrize(
    "sql,created,sources",
    [
        ("SELECT 1 AS id INTO t", NamedObject("t", T.TABLE, "created"), ()),
        (
            "SELECT * INTO TEMP t2 FROM t",
            NamedObject("t2", T.TABLE, "created"),
            (NamedObject("t", T.TABLE, "referenced"),),
        ),
        (
            "WITH c AS (SELECT 1) SELECT * INTO t FROM c",
            NamedObject("t", T.TABLE, "created"),
            (),
        ),
        ("SELECT 1 INTO t UNION SELECT 2", NamedObject("t", T.TABLE, "created"), ()),
        (
            "SELECT a.x INTO s.t FROM s.src a JOIN other b ON a.id = b.id",
            NamedObject("t", T.TABLE, "created", "s"),
            (
                NamedObject("src", T.TABLE, "referenced", "s"),
                NamedObject("other", T.TABLE, "referenced"),
            ),
        ),
    ],
)
def test_select_into_creates_its_table(sql, created, sources):
    """PostgreSQL 16.14 and YugabyteDB 2026.1.2 create the table for ``SELECT 1 AS id INTO t``;
    CockroachDB v24.3.18 rejects the form with SQLSTATE 42601."""
    assert _pg(sql) == StatementFacts("SELECT", "DML", (created,) + sources)


def test_a_plain_select_stays_a_query():
    assert _pg("SELECT * FROM t") == StatementFacts(
        "SELECT", "QUERY", (NamedObject("t", T.TABLE, "referenced"),)
    )


@pytest.mark.parametrize("dialect", ["duckdb", "sqlite"])
@pytest.mark.parametrize(
    "sql,names",
    [("SELECT 1 AS id INTO t", ["t"]), ("SELECT * INTO TEMP t2 FROM t", ["t2", "t"])],
)
def test_select_into_is_unchanged_for_other_dialects(dialect, sql, names):
    facts = read_statement_facts(sql, dialect=dialect)

    assert (facts.operation, facts.kind) == ("SELECT", "QUERY")
    assert facts.objects == tuple(NamedObject(n, T.TABLE, "referenced") for n in names)


HEAD_CASES = [
    (
        "CREATE OR REPLACE FUNCTION f() RETURNS TRIGGER AS $$ BEGIN RETURN NEW; END; $$"
        " LANGUAGE plpgsql",
        "CREATE",
        NamedObject("f", T.FUNCTION, "created"),
    ),
    (
        "CREATE FUNCTION f() RETURNS int BEGIN ATOMIC SELECT 1; END",
        "CREATE",
        NamedObject("f", T.FUNCTION, "created"),
    ),
    (
        'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"',
        "CREATE",
        NamedObject("uuid-ossp", T.EXTENSION, "created"),
    ),
    ("DROP EXTENSION my_ext", "DROP", NamedObject("my_ext", T.EXTENSION, "dropped")),
    (
        "ALTER SEQUENCE users_seq RESTART WITH 100",
        "ALTER",
        NamedObject("users_seq", T.SEQUENCE, "altered"),
    ),
    ("CREATE TYPE real_type FROM int", "CREATE", NamedObject("real_type", T.TYPE, "created")),
    (
        "CREATE UNLOGGED TABLE t (a int) TABLESPACE ts",
        "CREATE",
        NamedObject("t", T.TABLE, "created"),
    ),
    (
        "CREATE TABLE m (a int) WITH (fillfactor=70) TABLESPACE ts",
        "CREATE",
        NamedObject("m", T.TABLE, "created"),
    ),
    ("ALTER SCHEMA s RENAME TO t", "ALTER", NamedObject("s", T.SCHEMA, "altered")),
    (
        "CREATE UNLOGGED TABLE IF NOT EXISTS t (a int) TABLESPACE ts",
        "CREATE",
        NamedObject("t", T.TABLE, "created"),
    ),
]
HEAD_IDS = ["or_replace_function", "begin_atomic", "create_ext", "drop_ext", "alter_seq",
            "type_from", "unlogged_table", "storage_params", "alter_schema",
            "unlogged_if_not_exists"]  # fmt: skip


@pytest.mark.parametrize("sql,operation,named", HEAD_CASES, ids=HEAD_IDS)
def test_statements_the_grammar_leaves_opaque_are_named_from_their_head(sql, operation, named):
    facts = _pg(sql)

    assert (facts.operation, facts.kind, facts.objects) == (operation, "DDL", (named,))
    assert facts.opaque
    assert facts.diagnostic.startswith(named.type.value.lower().replace("_", " ") + ": ")
    assert facts.error is None


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE SCHEMA IF NOT EXISTS AUTHORIZATION joe",
        "CREATE EXTENSION IF NOT EXISTS AUTHORIZATION",
        "CREATE SEQUENCE IF NOT EXISTS",
        "CREATE TABLE IF NOT EXISTS",
    ],
)
def test_a_modifier_word_is_never_taken_for_the_name(sql):
    facts = _pg(sql)

    assert facts.objects == ()
    assert (facts.operation, facts.kind) == ("CREATE", "DDL")


def test_a_head_name_glued_to_a_no_break_space_stays_unnamed():
    facts = _pg("CREATE EXTENSION pgcrypto x")

    assert facts.objects == ()
    assert (facts.operation, facts.kind) == ("CREATE", "DDL")


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE INDEX CONCURRENTLY ix ON ONLY t (a)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix ON ONLY t (a)",
    ],
)
def test_concurrently_is_a_modifier_never_the_index_name(sql):
    facts = _pg(sql)
    assert facts.objects == (NamedObject("ix", T.INDEX, "created"),)


def test_drop_index_concurrently_names_the_index():
    assert _pg("DROP INDEX CONCURRENTLY IF EXISTS ix").objects == (
        NamedObject("ix", T.INDEX, "dropped"),
    )


@pytest.mark.parametrize("operation,tail", [("GRANT", "TO r"), ("REVOKE", "FROM r")])
@pytest.mark.parametrize(
    "privileges_on,expected",
    [
        ("SELECT ON t", NamedObject("t", T.TABLE, "referenced")),
        ("SELECT ON TABLE t", NamedObject("t", T.TABLE, "referenced")),
        ("SELECT ON s.t", NamedObject("t", T.TABLE, "referenced", "s")),
        ("SELECT ON TABLE s.t", NamedObject("t", T.TABLE, "referenced", "s")),
        ("SELECT, INSERT ON t", NamedObject("t", T.TABLE, "referenced")),
        ("SELECT (a) ON t", NamedObject("t", T.TABLE, "referenced")),
        ("ALL ON t", NamedObject("t", T.TABLE, "referenced")),
        ("USAGE ON SEQUENCE sq", NamedObject("sq", T.SEQUENCE, "referenced")),
        ("USAGE ON SCHEMA s", NamedObject("s", T.SCHEMA, "referenced")),
        ("CONNECT ON DATABASE d", NamedObject("d", T.DATABASE, "referenced")),
        ("USAGE ON TYPE ty", NamedObject("ty", T.TYPE, "referenced")),
        ("EXECUTE ON FUNCTION f", NamedObject("f", T.FUNCTION, "referenced")),
        ("EXECUTE ON FUNCTION s.f", NamedObject("f", T.FUNCTION, "referenced", "s")),
        ("EXECUTE ON PROCEDURE p", NamedObject("p", T.PROCEDURE, "referenced")),
    ],
)
def test_grant_and_revoke_are_ddl_that_reference_the_object_they_name(
    privileges_on, expected, operation, tail
):
    """GRANT and REVOKE change privileges, not the object, so the securable is only referenced.

    Measured 2026-10-24 on PostgreSQL 16.14: every form here runs on an existing object, and on
    a missing one fails after parsing (42P01 table or sequence, 3F000 schema, 3D000 database,
    42704 type, 42883 function), never with 42601.
    """
    facts = _pg(f"{operation} {privileges_on} {tail}")

    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert facts.objects == (expected,)
    assert facts.diagnostic is None


@pytest.mark.parametrize(
    "sql",
    [
        "GRANT SELECT ON t TO GROUP g",
        "GRANT SELECT ON t TO PUBLIC",
        "GRANT SELECT ON t TO u WITH GRANT OPTION",
        "REVOKE GRANT OPTION FOR SELECT ON t FROM u CASCADE",
        "REVOKE ALL ON t FROM u RESTRICT",
    ],
)
def test_grant_options_and_principals_do_not_change_the_securable(sql):
    # Measured 2026-10-24 on PostgreSQL 16.14: all five run.
    assert _pg(sql).objects == (NamedObject("t", T.TABLE, "referenced"),)


@pytest.mark.parametrize(
    "sql",
    [
        # sqlglot reads these as an unmodelled command: no single table is proven.
        "GRANT SELECT ON ALL TABLES IN SCHEMA s TO u",
        "GRANT ALL ON ALL SEQUENCES IN SCHEMA s TO u",
        "GRANT r TO u",
        "GRANT SELECT ON t1, t2 TO u",
        "GRANT USAGE ON FOREIGN SERVER fs TO u",
        # sqlglot holds a routine with a signature as a call, not as a name.
        "GRANT EXECUTE ON FUNCTION f(int) TO u",
        "GRANT EXECUTE ON PROCEDURE p(int) TO u",
        "REVOKE EXECUTE ON FUNCTION f(int) FROM u",
        # The catalog part of a table name is not read.
        "GRANT SELECT ON a.b.c TO u",
    ],
)
def test_grant_forms_that_prove_no_single_object_name_stay_opaque(sql):
    """Measured 2026-10-24 on PostgreSQL 16.14: all parse (``t1, t2`` grants on two tables;
    ``a.b.c`` is refused after parsing with 0A000, cross-database references).
    """
    facts = _pg(sql)

    assert facts.objects == ()
    assert facts.opaque
    assert facts.operation in {"GRANT", "REVOKE"}


@pytest.mark.parametrize(
    "sql", ["GRANT USAGE ON SCHEMA a.b TO u", "GRANT CONNECT ON DATABASE a.b TO u"]
)
def test_a_qualified_schema_or_database_is_not_named(sql):
    # Measured 2026-10-24 on PostgreSQL 16.14: both are syntax errors (42601).
    facts = _pg(sql)

    assert facts.objects == ()
    assert facts.opaque


@pytest.mark.parametrize("dialect", ["oracle"])
@pytest.mark.parametrize("sql", ["GRANT SELECT ON t TO r", "REVOKE SELECT ON t FROM r"])
def test_grant_and_revoke_keep_their_kind_on_other_dialects(sql, dialect):
    facts = read_statement_facts(sql, dialect=dialect)
    assert facts.kind == "UNKNOWN"


@pytest.mark.parametrize(
    "sql,named",
    [
        (
            "CREATE TABLE concurrently (a int) TABLESPACE ts",
            NamedObject("concurrently", T.TABLE, "created"),
        ),
        ("CREATE SEQUENCE concurrently", NamedObject("concurrently", T.SEQUENCE, "created")),
        (
            "CREATE INDEX CONCURRENTLY concurrently ON ONLY t (a)",
            NamedObject("concurrently", T.INDEX, "created"),
        ),
    ],
)
def test_concurrently_is_an_ordinary_name_except_as_the_index_modifier(sql, named):
    assert _pg(sql).objects == (named,)


@pytest.mark.parametrize(
    "sql,obj",
    [
        ("CREATE TABLE m (a int) TABLESPACE ts", NamedObject("m", T.TABLE, "created")),
        (
            "CREATE TABLE m (a int) WITH (fillfactor=70) TABLESPACE ts",
            NamedObject("m", T.TABLE, "created"),
        ),
        (
            "CREATE UNLOGGED TABLE IF NOT EXISTS s.t (a int) TABLESPACE ts",
            NamedObject("t", T.TABLE, "created", "s"),
        ),
        ("CREATE TABLE m TABLESPACE ts AS SELECT 1", NamedObject("m", T.TABLE, "created")),
        ("CREATE INDEX i ON m (a) TABLESPACE ts", NamedObject("i", T.INDEX, "created")),
        (
            "CREATE MATERIALIZED VIEW mv TABLESPACE ts AS SELECT 1",
            NamedObject("mv", T.MATERIALIZED_VIEW, "created"),
        ),
    ],
)
def test_a_tablespace_clause_is_named_in_the_diagnostic(sql, obj):
    """sqlglot 30.23 has no TABLESPACE clause in its PostgreSQL grammar and returns the whole
    statement as a command, so the object is named from the head and the clause is the reason."""
    facts = _pg(sql)

    assert facts.objects == (obj,)
    assert facts.diagnostic.endswith("postgres TABLESPACE clause is not modelled by the grammar")


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLESPACE ts LOCATION '/x'",
        "CREATE TABLE m (a int) WITHOUT OIDS",
        "CREATE TABLE tablespace (a int) WITHOUT OIDS",
        "CREATE TABLE IF NOT EXISTS tablespace (a int) WITHOUT OIDS",
        "CREATE LOB TABLESPACE ts MANAGED BY SYSTEM",
    ],
)
def test_a_command_without_a_tablespace_clause_keeps_the_generic_diagnostic(sql):
    assert "TABLESPACE clause" not in (_pg(sql).diagnostic or "")


def test_a_column_named_tablespace_is_read_normally():
    assert _pg("CREATE TABLE m (tablespace int)").diagnostic is None
