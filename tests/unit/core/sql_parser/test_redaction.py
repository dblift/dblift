"""String literals are masked and statements identified without echoing literals."""

import pytest

from dblift.core.sql_parser.redaction import describe_statement, mask_string_literals


@pytest.mark.parametrize("dialect", [None, "postgresql", "oracle", "sqlserver"])
@pytest.mark.parametrize(
    "sql, expected",
    [
        ("INSERT INTO missing_table VALUES ('a', 'b')", "INSERT INTO missing_table"),
        ("INSERT INTO t (a, b) VALUES ('x', 'y')", "INSERT INTO t"),
        ("CREATE USER app PASSWORD 'pw'", "CREATE USER app"),
        ('ALTER USER app IDENTIFIED BY "pw"', "ALTER USER app"),
        ("CREATE USER bob IDENTIFIED BY hunter2", "CREATE USER bob"),
        ("ALTER USER bob IDENTIFIED BY hunter2", "ALTER USER bob"),
        ("CREATE OR REPLACE VIEW s.v AS SELECT 1", "CREATE OR REPLACE VIEW s.v"),
        ("GRANT SELECT, INSERT ON t TO bob", "GRANT SELECT, INSERT ON t"),
        ("DELETE FROM t WHERE a = 1", "DELETE FROM t"),
        ("  UPDATE\n   t\n SET a = 'x'", "UPDATE t"),
        ("UPDATE s.t SET a = 1", "UPDATE s.t"),
        ("SET password=hunter2", "SET password"),
        ("DO $$ BEGIN PERFORM 1; END $$", "DO"),
        ("SELECT * FROM t", "SELECT"),
        ("-- note\nDROP TABLE IF EXISTS t", "DROP TABLE IF EXISTS t"),
    ],
)
def test_describe_statement_is_verb_and_target_only(dialect, sql, expected):
    assert describe_statement(sql, dialect) == expected


def test_describe_statement_keeps_a_quoted_target():
    assert describe_statement('INSERT INTO "My"."t" VALUES (1)', "postgresql") == (
        'INSERT INTO "My"."t"'
    )


def test_describe_statement_is_bounded():
    assert len(describe_statement("DROP TABLE " + "x" * 500)) <= 80


@pytest.mark.parametrize(
    "dialect, sql, expected",
    [
        (None, "INSERT INTO t VALUES ('a', 'it''s')", "INSERT INTO t VALUES ('?', '?')"),
        ("sqlite", "UPDATE t SET a = 'x'\nWHERE id = 1;", "UPDATE t SET a = '?'\nWHERE id = 1;"),
        ("postgresql", "SELECT $$secret$$, E'a\\'b', 1", "SELECT '?', '?', 1"),
        ("mysql", "ALTER USER u IDENTIFIED BY 'pw'", "ALTER USER u IDENTIFIED BY '?'"),
        (
            "oracle",
            "CREATE USER u IDENTIFIED BY \"x\" -- 'note'\nDEFAULT TABLESPACE users",
            None,
        ),
    ],
)
def test_mask_string_literals_keeps_the_statement_shape(dialect, sql, expected):
    masked = mask_string_literals(sql, dialect)

    for secret in ("secret", "'a'", "'pw'", "it''s"):
        assert secret not in masked
    if expected is not None:
        assert masked == expected


@pytest.mark.parametrize("dialect", [None, "postgresql", "oracle", "mysql", "sqlserver"])
@pytest.mark.parametrize(
    "sql, expected",
    [
        (
            "CREATE USER IF NOT EXISTS bob IDENTIFIED BY pw1",
            "CREATE USER IF NOT EXISTS bob IDENTIFIED BY ?",
        ),
        ("ALTER ROLE r PASSWORD pw4", "ALTER ROLE r PASSWORD ?"),
        ("ALTER ROLE r PASSWORD = pw4;", "ALTER ROLE r PASSWORD = ?;"),
        (
            "CREATE DATABASE LINK l CONNECT TO u IDENTIFIED BY pw12 USING 'x'",
            "CREATE DATABASE LINK l CONNECT TO u IDENTIFIED BY ? USING '?'",
        ),
        ("alter user u identified by /* c */ pw5", "alter user u identified by /* c */ ?"),
    ],
)
def test_mask_string_literals_masks_unquoted_credentials(dialect, sql, expected):
    assert mask_string_literals(sql, dialect) == expected


@pytest.mark.parametrize("dialect", [None, "postgresql", "oracle", "mysql", "sqlserver"])
def test_mask_string_literals_masks_a_quoted_credential(dialect):
    masked = mask_string_literals('ALTER USER u IDENTIFIED BY "pw9" PASSWORD EXPIRE', dialect)

    assert "pw9" not in masked
    assert masked.startswith("ALTER USER u IDENTIFIED BY ")


@pytest.mark.parametrize("dialect", [None, "postgresql", "oracle", "mysql", "sqlserver"])
def test_mask_string_literals_masks_a_quoted_credential_with_spaces(dialect):
    masked = mask_string_literals('ALTER USER u IDENTIFIED BY "p ""w" ACCOUNT UNLOCK', dialect)

    assert masked in (
        "ALTER USER u IDENTIFIED BY ? ACCOUNT UNLOCK",
        "ALTER USER u IDENTIFIED BY '?' ACCOUNT UNLOCK",
    )


def test_mask_string_literals_fails_closed_on_an_unterminated_quoted_credential():
    assert mask_string_literals('ALTER USER u IDENTIFIED BY "p w') == "ALTER USER u"


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("SELECT password FROM users", "SELECT password FROM users"),
        ("UPDATE t SET password = col2 WHERE id = 1", "UPDATE t SET password = col2 WHERE id = 1"),
        ("UPDATE t SET password = 'x'", "UPDATE t SET password = '?'"),
        ("CREATE ROLE r PASSWORD pw", "CREATE ROLE r PASSWORD ?"),
        ("ALTER LOGIN l WITH PASSWORD = pw", "ALTER LOGIN l WITH PASSWORD = ?"),
    ],
)
def test_password_value_is_masked_only_in_principal_ddl(sql, expected):
    assert mask_string_literals(sql) == expected


def test_mask_string_literals_handles_copy_data():
    sql = "COPY t (a) FROM stdin;\nSENTINEL-ROW\t42\n\\.\n"

    assert "SENTINEL-ROW" not in mask_string_literals(sql, "postgresql")


def test_mask_string_literals_fails_closed(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("tokenizer broke")

    monkeypatch.setattr("dblift.core.sql_parser.redaction.BaseTokenizer.tokenize", boom)

    assert mask_string_literals("INSERT INTO t VALUES ('secret')") == "INSERT"
    assert describe_statement("CREATE USER bob IDENTIFIED BY hunter2") == "CREATE"
