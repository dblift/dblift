"""Redshift statement facts: names for the forms the engine accepts, opaque for the rest.

Every statement below was sent to Redshift Serverless 1.0.485645 (psycopg 3.3.5, 2026-10-20,
temporary tables or a rolled-back transaction): the engine parses a statement before it resolves
names, so SQLSTATE 42601 marks text its grammar rejects and any other outcome a statement that
parsed. A statement the engine runs is read by its names; one the reader does not model names
nothing and says so.
"""

import pytest

from dblift.db.provider_registry import ProviderRegistry


def facts(sql):
    return ProviderRegistry.get_quirks("redshift").statement_facts(sql)


def names(sql):
    return tuple((o.name, o.type.value, o.role, o.schema) for o in facts(sql).objects)


@pytest.mark.parametrize(
    "sql, expected",
    [
        # SELECT ... INTO creates the table (temporary, schema-qualified or not): n01-n10.
        (
            "SELECT a INTO TEMP n1 FROM p1",
            (("n1", "TABLE", "created", None), ("p1", "TABLE", "referenced", None)),
        ),
        (
            "SELECT a INTO TEMPORARY TABLE n2 FROM p1",
            (("n2", "TABLE", "created", None), ("p1", "TABLE", "referenced", None)),
        ),
        (
            "SELECT a INTO TABLE s.n3 FROM p1",
            (("n3", "TABLE", "created", "s"), ("p1", "TABLE", "referenced", None)),
        ),
        (
            "SELECT a INTO n4 FROM p1 ORDER BY a LIMIT 1",
            (("n4", "TABLE", "created", None), ("p1", "TABLE", "referenced", None)),
        ),
        (
            "SELECT a INTO TEMP n6 FROM p1 UNION SELECT b FROM p2",
            (
                ("n6", "TABLE", "created", None),
                ("p1", "TABLE", "referenced", None),
                ("p2", "TABLE", "referenced", None),
            ),
        ),
        (
            "WITH w AS (SELECT a FROM p1) SELECT a INTO TEMP n10 FROM w",
            (("n10", "TABLE", "created", None), ("p1", "TABLE", "referenced", None)),
        ),
    ],
)
def test_select_into_creates_its_table(sql, expected):
    result = facts(sql)

    assert (result.operation, result.kind) == ("SELECT", "DML")
    assert names(sql) == expected
    assert not result.opaque


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("COMMENT ON TABLE s.t IS 'x'", (("t", "TABLE", "altered", "s"),)),
        ("COMMENT ON COLUMN s.t.a IS 'x'", (("t", "TABLE", "altered", "s"),)),
        ("COMMENT ON VIEW v IS 'x'", (("v", "VIEW", "altered", None),)),
    ],
)
def test_comment_on_names_the_commented_relation(sql, expected):
    result = facts(sql)

    assert (result.operation, result.kind) == ("COMMENT", "DDL")
    assert names(sql) == expected
    assert not result.opaque


@pytest.mark.parametrize(
    "sql",
    [
        "COMMENT ON MATERIALIZED VIEW mv IS 'x'",  # 42601
        "COMMENT ON FUNCTION f(int) IS 'x'",
        "COMMENT ON DATABASE dev IS 'x'",
    ],
)
def test_comment_on_other_targets_is_ddl_and_names_nothing(sql):
    result = facts(sql)

    assert result.kind == "DDL"
    assert result.objects == ()
    assert result.opaque


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("TRUNCATE t", (("t", "TABLE", "altered", None),)),
        ("TRUNCATE TABLE s.t", (("t", "TABLE", "altered", "s"),)),
    ],
)
def test_truncate_names_its_single_table(sql, expected):
    result = facts(sql)

    assert (result.operation, result.kind) == ("TRUNCATE", "DDL")
    assert names(sql) == expected
    assert not result.opaque


@pytest.mark.parametrize("sql", ["TRUNCATE a.b.c", "TRUNCATE t, u"])
def test_truncate_of_anything_else_names_nothing(sql):
    result = facts(sql)

    assert result.operation == "TRUNCATE"
    assert result.objects == ()
    assert result.opaque


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("CREATE SCHEMA s", (("s", "SCHEMA", "created", None),)),
        ("CREATE SCHEMA IF NOT EXISTS s", (("s", "SCHEMA", "created", None),)),
        ("DROP SCHEMA s CASCADE", (("s", "SCHEMA", "dropped", None),)),
        ("DROP SCHEMA IF EXISTS s", (("s", "SCHEMA", "dropped", None),)),
    ],
)
def test_schema_statements_name_the_schema(sql, expected):
    result = facts(sql)

    assert result.kind == "DDL"
    assert names(sql) == expected
    assert not result.opaque


@pytest.mark.parametrize(
    "sql",
    [
        # a two-part name is database.schema on Redshift (3D000 "producer database ... rs_a")
        'CREATE SCHEMA "rs_a"."rs_b"',
        "DROP SCHEMA a.b",
        # schema elements create tables as well; QUOTA and AUTHORIZATION are not read
        "CREATE SCHEMA s CREATE TABLE t (a int)",
        "CREATE SCHEMA s QUOTA 1 GB",
        "CREATE SCHEMA IF NOT EXISTS s AUTHORIZATION u",
        "DROP SCHEMA a, b CASCADE",
        "CREATE EXTERNAL SCHEMA ext FROM DATA CATALOG DATABASE 'd' IAM_ROLE 'arn:aws:iam::1:role/r'",
    ],
)
def test_schema_statements_the_reader_cannot_prove_name_nothing(sql):
    result = facts(sql)

    assert result.kind == "DDL"
    assert result.objects == ()
    assert result.opaque


@pytest.mark.parametrize(
    "sql, expected",
    [
        (
            "CREATE MATERIALIZED VIEW mv AUTO REFRESH YES AS SELECT * FROM t",
            (("mv", "MATERIALIZED_VIEW", "created", None), ("t", "TABLE", "referenced", None)),
        ),
        (
            "DROP MATERIALIZED VIEW IF EXISTS mv",
            (("mv", "MATERIALIZED_VIEW", "dropped", None),),
        ),
        ("DROP VIEW IF EXISTS v CASCADE", (("v", "VIEW", "dropped", None),)),
    ],
)
def test_materialized_views_are_not_plain_views(sql, expected):
    assert names(sql) == expected
    assert not facts(sql).opaque


@pytest.mark.parametrize(
    "sql, expected",
    [
        (
            "CREATE TABLE s.t (a int, b varchar(10) ENCODE zstd) DISTSTYLE KEY DISTKEY(a) SORTKEY(b)",
            (("t", "TABLE", "created", "s"),),
        ),
        ("CREATE TABLE IF NOT EXISTS t (a int) BACKUP NO", (("t", "TABLE", "created", None),)),
        ("CREATE TEMP TABLE t AS SELECT 1", (("t", "TABLE", "created", None),)),
        (
            "CREATE EXTERNAL TABLE spectrum.t (a int) STORED AS PARQUET LOCATION 's3://x/'",
            (("t", "TABLE", "created", "spectrum"),),
        ),
        (
            "CREATE VIEW v AS SELECT * FROM public.t WITH NO SCHEMA BINDING",
            (("v", "VIEW", "created", None), ("t", "TABLE", "referenced", "public")),
        ),
        (
            "CREATE PROCEDURE p() AS $$ BEGIN INSERT INTO t VALUES (1); END; $$ LANGUAGE plpgsql",
            (("p", "PROCEDURE", "created", None),),
        ),
        (
            "CREATE OR REPLACE FUNCTION s.f(a int) RETURNS int IMMUTABLE AS $$ SELECT $1 $$ LANGUAGE sql",
            (("f", "FUNCTION", "created", "s"),),
        ),
        ("DROP PROCEDURE p(int)", (("p", "PROCEDURE", "dropped", None),)),
        (
            "DROP TABLE IF EXISTS a, s.b CASCADE",
            (("a", "TABLE", "dropped", None), ("b", "TABLE", "dropped", "s")),
        ),
        ("ALTER TABLE t ALTER DISTKEY a", (("t", "TABLE", "altered", None),)),
        ("ALTER TABLE t ADD COLUMN c int ENCODE zstd", (("t", "TABLE", "altered", None),)),
        ('CREATE TABLE "AbC" (a int)', (("AbC", "TABLE", "created", None),)),
    ],
)
def test_redshift_ddl_is_named_as_written(sql, expected):
    assert names(sql) == expected
    assert not facts(sql).opaque


@pytest.mark.parametrize(
    "sql, operation, kind",
    [
        (
            "CREATE LIBRARY l LANGUAGE plpythonu FROM 's3://b/l.zip' IAM_ROLE 'arn:aws:iam::1:role/r'",
            "CREATE",
            "DDL",
        ),
        ("DROP LIBRARY l", "DROP", "DDL"),
        (
            "UNLOAD ('select * from t') TO 's3://b/p' IAM_ROLE 'arn:aws:iam::1:role/r'",
            "UNLOAD",
            "UNKNOWN",
        ),
        (
            "CREATE EXTERNAL FUNCTION f(int) RETURNS int LAMBDA 'l' IAM_ROLE 'arn:aws:iam::1:role/r'",
            "CREATE",
            "DDL",
        ),
        ("CALL p()", "CALL", "UNKNOWN"),
    ],
)
def test_redshift_only_statements_are_opaque_not_guessed(sql, operation, kind):
    result = facts(sql)

    assert (result.operation, result.kind) == (operation, kind)
    assert result.objects == ()
    assert result.opaque


def test_alter_table_append_names_its_target_and_says_the_source_is_unread():
    result = facts("ALTER TABLE t APPEND FROM u")

    assert names("ALTER TABLE t APPEND FROM u") == (("t", "TABLE", "altered", None),)
    assert result.opaque


@pytest.mark.parametrize(
    "sql, expected",
    [
        (
            "COPY s.t (a, b) FROM 's3://b/p' IAM_ROLE default CSV IGNOREHEADER 1",
            (("t", "TABLE", "altered", "s"),),
        ),
        (
            "COPY t FROM 's3://b/p' IAM_ROLE 'arn:aws:iam::1:role/r' FORMAT AS CSV DELIMITER ','",
            (("t", "TABLE", "altered", None),),
        ),
    ],
)
def test_copy_from_names_the_loaded_table(sql, expected):
    result = facts(sql)

    assert (result.operation, result.kind) == ("COPY", "DML")
    assert result.events == frozenset({"INSERT"})
    assert names(sql) == expected


@pytest.mark.parametrize(
    "sql, schema, target",
    [
        (
            "MERGE INTO t USING s ON t.a = s.a WHEN MATCHED THEN UPDATE SET b = s.b "
            "WHEN NOT MATCHED THEN INSERT VALUES (s.a, s.b)",
            None,
            "t",
        ),
        (
            'MERGE INTO "Sales"."Order Items" USING s ON "Order Items".a = s.a WHEN MATCHED THEN DELETE',
            "Sales",
            "Sales.Order Items",
        ),
    ],
)
def test_merge_names_its_target_and_leaves_sources_and_actions_unread(sql, schema, target):
    result = facts(sql)

    assert (result.operation, result.kind) == ("MERGE", "DML")
    assert [(o.role, o.schema) for o in result.objects] == [("altered", schema)]
    assert result.target == target
    assert result.opaque


def test_grant_is_ddl_and_names_nothing():
    result = facts("GRANT SELECT ON t TO PUBLIC")

    assert (result.operation, result.kind) == ("GRANT", "DDL")
    assert result.objects == ()
    assert result.opaque


@pytest.mark.parametrize(
    "sql, table, referenced, predicate",
    [
        ("UPDATE t AS r SET b = 1 FROM u WHERE r.a = u.a", "t", ("u",), "r.a = u.a"),
        ("UPDATE t r SET b = 1 WHERE r.a = 1", "t", (), "r.a = 1"),
        ("DELETE FROM t USING u WHERE t.a = u.a", "t", ("u",), "t.a = u.a"),
        ("DELETE t WHERE a = 1", "t", (), "a = 1"),
        ("INSERT INTO t (a, b) SELECT a, b FROM u", "t", ("u",), None),
        (
            "WITH x AS (SELECT 1 AS a) UPDATE t SET b = 2 FROM x WHERE t.a = x.a",
            "t",
            (),
            "t.a = x.a",
        ),
    ],
)
def test_dml_names_its_bare_target(sql, table, referenced, predicate):
    result = facts(sql)

    assert result.kind == "DML"
    assert result.target == table
    assert result.target_sql == table
    assert result.predicate == predicate
    assert names(sql) == (
        (table, "TABLE", "altered", None),
        *((name, "TABLE", "referenced", None) for name in referenced),
    )


def test_a_cte_that_shadows_a_table_keeps_only_the_outer_target():
    result = facts("WITH t AS (SELECT * FROM t) DELETE FROM u")

    assert names("WITH t AS (SELECT * FROM t) DELETE FROM u") == (("u", "TABLE", "altered", None),)
    assert result.opaque


def test_a_no_break_space_after_a_name_is_part_of_the_name_so_nothing_is_named():
    # q10/q11: the engine looks for the relation "t<U+00A0>" (42P01)
    result = facts("DELETE FROM t ")

    assert result.objects == ()
    assert result.opaque


@pytest.mark.parametrize(
    "sql, operation",
    [
        # q1-q3, b01-b04: brackets around a name are dropped, a quoted name inside keeps its own
        # quoting rules (`["a""b"]` creates a"b), a space inside is a syntax error
        ("CREATE TABLE [plain] (id int)", "CREATE"),
        ('CREATE TABLE ["a""b"] (id int)', "CREATE"),
        ("CREATE INDEX [i] ON [dbo].[t] ([c])", "CREATE"),
        ("DROP INDEX [idx]", "DROP"),
        ("ALTER TABLE [s].[t] ADD COLUMN c int", "ALTER"),
    ],
)
def test_a_bracketed_name_is_not_read(sql, operation):
    result = facts(sql)

    assert (result.operation, result.kind) == (operation, "DDL")
    assert result.objects == ()
    assert result.opaque


def test_brackets_after_the_head_are_not_a_name():
    sql = "ALTER TABLE t ADD COLUMN c super DEFAULT json_parse('[1]')"

    assert names(sql) == (("t", "TABLE", "altered", None),)
