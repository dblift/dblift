"""A statement the facts reader leaves unread is reported, never rated SAFE by silence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dblift.core.migration.sql.lint import lint_script

pytestmark = pytest.mark.unit

_UNKNOWN = "FROBNICATE the widgets;"
_ORACLE_BLOCK = "BEGIN\n  DELETE FROM emp;\nEND;\n/\n"
_ORACLE_EXECUTE = "EXECUTE IMMEDIATE 'DROP TABLE emp';\n"
_DB2_COMPOUND = "BEGIN ATOMIC\n  DELETE FROM emp;\nEND\n"

UNREAD = [
    ("postgresql", _UNKNOWN),
    ("mysql", _UNKNOWN),
    ("oracle", _UNKNOWN),
    ("db2", _UNKNOWN),
    ("sqlite", _UNKNOWN),
    ("sqlserver", _UNKNOWN),
    ("oracle", _ORACLE_BLOCK),
    ("oracle", _ORACLE_EXECUTE),
    ("db2", _DB2_COMPOUND),
]

ENVELOPES = [
    ("postgresql", "BEGIN;\nSET search_path = app;\nSAVEPOINT s;\nRELEASE SAVEPOINT s;\nCOMMIT;"),
    ("postgresql", "START TRANSACTION;\nROLLBACK;"),
    ("mysql", "USE app;\nSET foreign_key_checks = 0;\nSTART TRANSACTION;\nCOMMIT;"),
    ("sqlite", "BEGIN;\nSAVEPOINT s;\nRELEASE s;\nCOMMIT;"),
    ("db2", "SET CURRENT SCHEMA = app;\nCOMMIT;"),
    ("oracle", "SET TRANSACTION READ WRITE;\nCOMMIT;"),
    ("sqlserver", "SET NOCOUNT ON;\nUSE app;\nBEGIN TRANSACTION;\nCOMMIT TRANSACTION;"),
    ("postgresql", "-- only a comment\n"),
    ("mysql", "SHOW TABLES;\nDESCRIBE users;"),
]


@pytest.mark.parametrize("dialect, sql", UNREAD)
def test_unread_statement_is_review_not_safe(dialect, sql):
    result = lint_script(sql, dialect)

    assert result.verdict == "REVIEW", (result.verdict, result.findings, result.errors)
    assert [f.code for f in result.findings] == ["statement-not-analysed"]
    assert result.findings[0].severity == "info"


@pytest.mark.parametrize("dialect, sql", [c for c in UNREAD if c[1] != _UNKNOWN])
def test_procedural_block_message_says_effects_are_not_modelled(dialect, sql):
    finding = lint_script(sql, dialect).findings[0]

    assert "procedural block: effects not modelled" in finding.message


@pytest.mark.parametrize("dialect", ["postgresql", "mysql", "oracle", "db2", "sqlite"])
def test_unread_message_names_the_reason(dialect):
    finding = lint_script(_UNKNOWN, dialect).findings[0]

    assert "FROBNICATE" in finding.message
    assert "not modelled" in finding.message or "not classified" in finding.message


@pytest.mark.parametrize("dialect, sql", ENVELOPES)
def test_transaction_and_session_envelopes_stay_safe(dialect, sql):
    result = lint_script(sql, dialect)

    assert (result.verdict, result.findings, result.errors) == ("SAFE", (), ())


def test_unread_statement_beside_read_ones_flags_only_itself():
    sql = "CREATE TABLE t (id INT);\nFROBNICATE the widgets;\nSET x = 1;"

    result = lint_script(sql, "postgresql")

    assert [(f.code, f.statement) for f in result.findings] == [("statement-not-analysed", 1)]


def test_allow_directive_accepts_an_unread_statement():
    result = lint_script("-- dblift:allow statement-not-analysed\n" + _UNKNOWN, "postgresql")

    assert result.verdict == "SAFE"


def _cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dblift.cli.main", "--log-dir", str(tmp_path / "logs"), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "DBLIFT_DISABLE_CLI_EXTENSIONS": "1"},
    )


@pytest.mark.parametrize("dialect, sql", UNREAD)
def test_cli_validate_sql_rates_unread_statement_review(tmp_path, dialect, sql):
    script = tmp_path / "V1__x.sql"
    script.write_text(sql)

    proc = _cli(
        tmp_path, "validate-sql", "--dialect", dialect, "--format", "json", "--files", str(script)
    )

    scripts = json.loads(proc.stdout)["scripts"]
    assert [s["verdict"] for s in scripts] == ["REVIEW"], proc.stdout
    assert [f["code"] for f in scripts[0]["findings"]] == ["statement-not-analysed"]
    assert proc.returncode == 0, proc.stderr


def test_cli_dry_run_analysis_marks_unread_statement(tmp_path):
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    (scripts / "V1__x.sql").write_text(_UNKNOWN)

    proc = _cli(
        tmp_path,
        "--scripts",
        str(scripts),
        "--db-url",
        f"sqlite:///{tmp_path / 't.db'}",
        "migrate",
        "--dry-run",
        "--format",
        "json",
    )

    analysis = json.loads(proc.stdout)["migrations"][0]["analysis"]
    assert analysis["verdict"] == "REVIEW", proc.stdout
    assert [f["code"] for f in analysis["findings"]] == ["statement-not-analysed"]


NON_DATA = [
    ("postgresql", "GRANT SELECT ON t TO u;"),
    ("postgresql", "REVOKE SELECT ON t FROM u;"),
    ("postgresql", "COMMENT ON TABLE t IS 'x';"),
    ("postgresql", "EXPLAIN SELECT 1;"),
    ("postgresql", "ANALYZE t;"),
    ("postgresql", "VACUUM t;"),
    ("mysql", "ANALYZE TABLE t;"),
    ("mysql", "GRANT SELECT ON t TO u;"),
    ("sqlite", "PRAGMA foreign_keys = ON;"),
    ("sqlite", "PRAGMA table_info(t);"),
    ("sqlite", "VACUUM;"),
    ("sqlite", "EXPLAIN QUERY PLAN SELECT 1;"),
    ("oracle", "GRANT SELECT ON t TO u;"),
    ("oracle", "COMMENT ON TABLE t IS 'x';"),
    ("db2", "COMMENT ON TABLE t IS 'x';"),
    ("sqlserver", "GRANT SELECT ON t TO u;"),
    ("mysql", "SHOW TABLES;"),
    ("mysql", "DESC t;"),
]

STILL_UNREAD = [
    ("postgresql", "EXPLAIN ANALYZE DELETE FROM t;"),
    ("postgresql", "EXPLAIN (ANALYZE, VERBOSE) DELETE FROM t;"),
    ("postgresql", "REINDEX TABLE t;"),
    ("mysql", "CALL p();"),
]


@pytest.mark.parametrize("dialect, sql", NON_DATA)
def test_recognised_non_data_head_stays_safe_when_unread(dialect, sql):
    result = lint_script(sql, dialect)

    assert (result.verdict, result.findings) == ("SAFE", ()), result


@pytest.mark.parametrize("dialect, sql", STILL_UNREAD)
def test_statements_beside_the_allow_list_stay_review(dialect, sql):
    result = lint_script(sql, dialect)

    assert result.verdict == "REVIEW", result
    assert [f.code for f in result.findings] == ["statement-not-analysed"]


# --- comments cannot hide the keyword that decides ------------------------------------------

COMMENT_BYPASS = [
    ("postgresql", "EXPLAIN /*x*/ ANALYZE DELETE FROM t;"),
    ("postgresql", "EXPLAIN -- c\n ANALYZE DELETE FROM t;"),
    ("mysql", "SET /*c*/ GLOBAL x = 1;"),
    ("sqlite", "/* c */ SET GLOBAL x = 1;"),
    ("mysql", "/* c */ SET GLOBAL x = 1;"),
]

EXECUTABLE_COMMENTS = [
    ("mysql", "/*! DELETE FROM t */;"),
    ("mysql", "/*!50000 DELETE FROM t */;"),
    ("mariadb", "/*! DELETE FROM t */;"),
    ("mariadb", "/*!50000 DELETE FROM t */;"),
    ("mysql", "SET /*!50000 GLOBAL */ x = 1;"),
]

SET_ESCALATIONS = [
    "SET GLOBAL x = 1;",
    "SET PERSIST x = 1;",
    "SET PERSIST_ONLY x = 1;",
    "SET PASSWORD = 'x';",
    "SET @@GLOBAL.x = 1;",
    "SET @@global.sql_mode = '';",
    "SET @@PERSIST.x = 1;",
    "SET @@persist_only.x = 1;",
    "SET @@session.a = 1, GLOBAL b = 2;",
]


@pytest.mark.parametrize("dialect, sql", COMMENT_BYPASS)
def test_a_comment_between_head_keywords_does_not_exempt(dialect, sql):
    result = lint_script(sql, dialect)

    assert result.verdict == "REVIEW", result
    assert [f.code for f in result.findings] == ["statement-not-analysed"]


@pytest.mark.parametrize("dialect, sql", EXECUTABLE_COMMENTS)
def test_a_mysql_executable_comment_is_not_comment_only(dialect, sql):
    result = lint_script(sql, dialect)

    assert result.verdict == "REVIEW", result
    assert [f.code for f in result.findings] == ["statement-not-analysed"]


@pytest.mark.parametrize("sql", SET_ESCALATIONS)
def test_set_that_reaches_the_server_or_an_account_is_reported(sql):
    result = lint_script(sql, "mysql")

    assert result.verdict == "REVIEW", result
    assert [f.code for f in result.findings] == ["statement-not-analysed"]


@pytest.mark.parametrize(
    "dialect, sql",
    [
        ("mysql", "SET SESSION sql_mode = '';"),
        ("mysql", "SET @@session.sql_mode = '';"),
        ("mysql", "COMMENT ON TABLE t IS 'x';"),
        ("duckdb", "COMMENT ON TABLE t IS 'x';"),
        ("sqlite", "/* c */ pragma foreign_keys = on;"),
        ("sqlite", "-- c\nPRAGMA foreign_keys = on;"),
        ("postgresql", "grant select on t to u;"),
        ("postgresql", "ExPlAiN select 1;"),
        ("postgresql", "VACUUM (VERBOSE) t;"),
        ("sqlserver", "DENY SELECT ON t TO u;"),
        ("postgresql", "VACUUM (FULL FALSE) t;"),
        ("mysql", "LOCK TABLES t READ;\nUNLOCK TABLES;"),
    ],
)
def test_more_non_data_heads_stay_safe(dialect, sql):
    result = lint_script(sql, dialect)

    assert (result.verdict, result.findings) == ("SAFE", ()), result


@pytest.mark.parametrize(
    "sql",
    [
        "VACUUM FULL t;",
        "VACUUM (FULL) t;",
        "VACUUM FREEZE FULL t;",
        "Vacuum Full t;",
        "vacuum (full, verbose) t;",
        "VACUUM /*x*/ FULL t;",
        "explain (analyze) delete from t;",
    ],
)
def test_vacuum_full_and_explain_analyze_are_reported_in_any_form(sql):
    result = lint_script(sql, "postgresql")  # VACUUM FULL has its lock finding as well

    assert result.verdict == "REVIEW", result
    assert result.findings


@pytest.mark.parametrize("dialect", ["oracle", "db2", "snowflake", "sqlserver"])
def test_execute_immediate_is_a_procedural_block_in_any_case(dialect):
    finding = lint_script("execute immediate 'drop table emp';\n", dialect).findings[0]

    assert "procedural block: effects not modelled" in finding.message


@pytest.mark.parametrize("sql", ["VACUUM FULL t;", "VACUUM (FULL) t;", "VACUUM FREEZE FULL t;"])
@pytest.mark.parametrize("dialect", ["mysql", "duckdb"])
def test_vacuum_full_is_reported_where_no_lock_rule_speaks_for_it(dialect, sql):
    result = lint_script(sql, dialect)

    assert [f.code for f in result.findings] == ["statement-not-analysed"], result


@pytest.mark.parametrize(
    "dialect, sql",
    [
        ("mariadb", "/*M!100100 DELETE FROM t */;"),
        ("mariadb", "/*M!100100 DELETE FROM t */"),
        ("mariadb", "SET /*M!100100 GLOBAL */ x = 1;"),
        ("mysql", "SET /*M!100100 GLOBAL */ x = 1;"),
    ],
)
def test_a_mariadb_executable_comment_is_reported(dialect, sql):
    result = lint_script(sql, dialect)

    assert result.verdict == "REVIEW", result
    assert [f.code for f in result.findings] == ["statement-not-analysed"]


def test_mysql_reads_a_mariadb_executable_comment_as_a_comment():
    # MySQL skips /*M! ... */, so the script holds no statement (MariaDB runs it: see above).
    result = lint_script("/*M!100100 DELETE FROM t */;", "mysql")

    assert (result.verdict, result.findings) == ("SAFE", ())


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
@pytest.mark.parametrize("sql", ["SET # c\n GLOBAL x = 1;", "# c\nSET GLOBAL x = 1;"])
def test_a_hash_comment_does_not_hide_set_global_where_hash_is_a_comment(dialect, sql):
    result = lint_script(sql, dialect)

    assert result.verdict == "REVIEW", result
    assert [f.code for f in result.findings] == ["statement-not-analysed"]


def test_a_hash_comment_is_not_a_comment_where_the_dialect_has_none():
    # PostgreSQL reads "# c" as text: the statement is unrecognised, so it is reported.
    result = lint_script("# c\nSET search_path = a;", "postgresql")

    assert result.verdict == "REVIEW", result


@pytest.mark.parametrize(
    "dialect", ["postgresql", "mysql", "mariadb", "oracle", "sqlserver", "db2"]
)
@pytest.mark.parametrize(
    "sql", ["-- c\n", "/* c */", "/* c */;", "-- c\n;", ";", "/* a */ ; /* b */"]
)
def test_comment_only_text_never_reaches_the_statement_list(dialect, sql):
    from dblift.core.migration.sql.script_analysis import analyse_script

    assert analyse_script(sql, dialect).statements == ()


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
def test_hash_comment_only_text_never_reaches_the_statement_list(dialect):
    from dblift.core.migration.sql.script_analysis import analyse_script

    assert analyse_script("# c\n", dialect).statements == ()
