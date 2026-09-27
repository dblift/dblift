"""Tests for SQL*Plus context integration in ExecutionEngine."""

from unittest.mock import MagicMock, patch

import pytest

from dblift.core.exceptions import TransactionAbortedError
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.formats import MigrationFormat
from dblift.core.migration.migration import Migration
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.db.plugins.oracle.parser.sqlplus_context import SqlplusContext


def _make_engine(dialect="oracle"):
    provider = MagicMock()
    provider.supports_transactions.return_value = True
    provider.connection = None  # no native connection in unit tests
    sql_analyzer = MagicMock()
    sql_analyzer.dialect = dialect
    log = MagicMock()
    config = MagicMock()
    config.database.type.value = dialect
    config.database.url = "oracle+oracledb://host:1521?service_name=XE"
    return ExecutionEngine(provider=provider, sql_analyzer=sql_analyzer, log=log, config=config)


def _make_sql_migration(content: str) -> Migration:
    m = MagicMock(spec=Migration)
    m.format = MigrationFormat.SQL
    m.content = content
    m.script_name = "V1__test.sql"
    return m


class TestSqlplusContextExtraction:
    def test_context_extracted_for_oracle(self):
        engine = _make_engine("oracle")
        migration = _make_sql_migration("SET SERVEROUTPUT ON\nSELECT 1 FROM DUAL;")
        result = MagicMock()
        result.has_error.return_value = False

        engine._parse_sql_statements(migration, result)

        assert engine._current_sqlplus_ctx is not None
        assert engine._current_sqlplus_ctx.serveroutput is True

    def test_no_context_for_non_oracle(self):
        engine = _make_engine("postgresql")
        migration = _make_sql_migration("SET SERVEROUTPUT ON\nSELECT 1;")
        result = MagicMock()
        result.has_error.return_value = False

        engine._parse_sql_statements(migration, result)

        assert engine._current_sqlplus_ctx is None

    def test_define_substitution_applied_before_parsing(self):
        engine = _make_engine("oracle")
        migration = _make_sql_migration("DEFINE owner = APP_SCHEMA\nSELECT * FROM &owner.users;")
        result = MagicMock()

        engine._parse_sql_statements(migration, result)

        # The analyzer receives script text after SQLPlus substitution.
        content_arg = engine.sql_analyzer.split_statements.call_args.args[0]
        assert content_arg is not None
        assert "&owner" not in content_arg
        assert "APP_SCHEMA" in content_arg

    def test_define_off_skips_substitution(self):
        engine = _make_engine("oracle")
        migration = _make_sql_migration(
            "SET DEFINE OFF\nDEFINE owner = APP\nSELECT * FROM &owner.t;"
        )
        result = MagicMock()

        engine._parse_sql_statements(migration, result)

        ctx = engine._current_sqlplus_ctx
        assert ctx.define_on is False

    def test_prompt_messages_logged(self):
        engine = _make_engine("oracle")
        migration = _make_sql_migration("PROMPT Starting data migration\nSELECT 1 FROM DUAL;")
        result = MagicMock()

        engine._parse_sql_statements(migration, result)

        log_calls = [str(c) for c in engine.log.info.call_args_list]
        assert any("Starting data migration" in c for c in log_calls)


# The directive-stripping script from the release test protocol, with
# apostrophes in the free-text directives.
SQLPLUS_DIRECTIVES_SCRIPT = """SET SERVEROUTPUT ON
SET LINESIZE 200
SET PAGESIZE 0
SET FEEDBACK OFF
SET ECHO OFF
SET VERIFY OFF
SET DEFINE ON
SET TERMOUT ON
SPOOL /tmp/dblift_test.log
SPOOL OFF
PROMPT Starting migration V10's objects
REMARK This is the customer's comment
REM Another comment style, don't run twice
DEFINE migration_label = V10_test
COLUMN username FORMAT A30
TIMING START migration_v10
TIMING STOP
DESCRIBE DBLIFT_TEST.USERS
CLEAR SCREEN
TTITLE 'Migration Report'
BTITLE 'End'
REPHEADER 'Header'
REPFOOTER 'Footer'
PAUSE
VARIABLE v_count NUMBER
PRINT v_count
BREAK ON username
COMPUTE COUNT OF id ON username
-- Actual SQL to verify migration applied:
CREATE TABLE DBLIFT_TEST.sqlplus_test (id NUMBER PRIMARY KEY, label VARCHAR2(100));
PROMPT Creating customer's table
CREATE TABLE DBLIFT_TEST.sp_a (id NUMBER);
REM it's q'[--]' next
CREATE TABLE DBLIFT_TEST.sp_b (v VARCHAR2(20) DEFAULT q'[--]');
"""


def _oracle_statements(content: str) -> list:
    engine = _make_engine("oracle")
    engine.sql_analyzer = SqlAnalyzer(dialect="oracle", logger=engine.log)
    return engine._parse_sql_statements(_make_sql_migration(content), MagicMock())


class TestSqlplusDirectiveApostrophes:
    """An apostrophe in a directive line does not open a literal.

    Before the fix the tokenizer read ``customer's`` as the start of a
    string running to the next apostrophe, so every statement in between
    was dropped along with the directive, and ``migrate`` still succeeded.
    """

    def test_five_line_script_runs_every_create(self):
        statements = _oracle_statements(
            "PROMPT Creating customer's table\n"
            "CREATE TABLE a (id NUMBER);\n"
            "REM don't run twice\n"
            "CREATE TABLE b (id NUMBER);\n"
            "CREATE TABLE c (id NUMBER);\n"
        )

        assert statements == [
            "CREATE TABLE a (id NUMBER);",
            "CREATE TABLE b (id NUMBER);",
            "CREATE TABLE c (id NUMBER);",
        ]

    @pytest.mark.parametrize(
        "directive",
        [
            "PROMPT Creating customer's table",
            "REM don't run twice",
            "REMARK it's fine",
            'PROMPT say "hi',
            "  prompt it's indented",
        ],
    )
    def test_lone_directive_with_quote_keeps_next_statements(self, directive):
        statements = _oracle_statements(
            f"CREATE TABLE a (id NUMBER);\n{directive}\n"
            "CREATE TABLE b (id NUMBER);\nCREATE TABLE c (v VARCHAR2(9) DEFAULT 'x');\n"
        )

        assert statements == [
            "CREATE TABLE a (id NUMBER);",
            "CREATE TABLE b (id NUMBER);",
            "CREATE TABLE c (v VARCHAR2(9) DEFAULT 'x');",
        ]

    def test_release_protocol_directive_block_with_apostrophes(self):
        statements = _oracle_statements(SQLPLUS_DIRECTIVES_SCRIPT)

        assert statements == [
            "CREATE TABLE DBLIFT_TEST.sqlplus_test "
            "(id NUMBER PRIMARY KEY, label VARCHAR2(100));",
            "CREATE TABLE DBLIFT_TEST.sp_a (id NUMBER);",
            "CREATE TABLE DBLIFT_TEST.sp_b (v VARCHAR2(20) DEFAULT q'[--]');",
        ]

    def test_whenever_line_still_reaches_the_executor(self):
        statements = _oracle_statements(
            "WHENEVER SQLERROR CONTINUE\nPROMPT it's next\nCREATE TABLE a (id NUMBER);\n"
        )

        assert statements == ["WHENEVER SQLERROR CONTINUE;", "CREATE TABLE a (id NUMBER);"]

    def test_trailing_comment_on_directive_line_is_a_comment(self):
        engine = _make_engine("oracle")
        migration = _make_sql_migration(
            "WHENEVER SQLERROR CONTINUE -- it's fine\n"
            "DEFINE owner = APP -- the owner's schema\n"
            "PROMPT Loading -- don't\n"
            "SELECT * FROM &owner..t;\n"
        )
        engine.sql_analyzer = SqlAnalyzer(dialect="oracle", logger=engine.log)

        statements = engine._parse_sql_statements(migration, MagicMock())

        assert engine._current_sqlplus_ctx.defines == {"OWNER": "APP"}
        assert engine._current_sqlplus_ctx.prompts == ["Loading"]
        assert statements == ["WHENEVER SQLERROR CONTINUE;", "SELECT * FROM APP.t;"]

    @pytest.mark.parametrize(
        "block",
        [
            # A multi-line literal whose lines look like directives.
            "BEGIN\n"
            "  EXECUTE IMMEDIATE 'CREATE TABLE x (\n"
            "PROMPT it''s not a directive\n"
            "REM nor this\n"
            "    id NUMBER)';\n"
            "END;",
            # EXECUTE / EXEC lines inside a block are PL/SQL, not directives.
            "BEGIN\n  EXECUTE IMMEDIATE\n    'CREATE TABLE x (id NUMBER)';\n"
            "  EXEC_PROC('it''s');\nEND;",
            "CREATE OR REPLACE PROCEDURE p AS\nBEGIN\n"
            "  EXECUTE IMMEDIATE 'INSERT INTO t VALUES (\n'\n"
            "    || '''don''''t'')';\nEND;",
        ],
        ids=["literal-lines", "execute-lines", "procedure"],
    )
    def test_directive_keywords_inside_plsql_are_kept(self, block):
        statements = _oracle_statements(
            f"PROMPT it's a block\n{block}\n/\nREM don't\nCREATE TABLE y (id NUMBER);\n"
        )

        assert statements == [block, "CREATE TABLE y (id NUMBER);"]

    def test_directive_keywords_inside_multi_line_literal_are_kept(self):
        insert = "INSERT INTO t (v) VALUES ('first line\nPROMPT it''s data\nSET x ON\n');"

        statements = _oracle_statements(f"{insert}\nCREATE TABLE y (id NUMBER);\n")

        assert statements == [insert, "CREATE TABLE y (id NUMBER);"]


class TestWheneverSqlerrorContinue:
    def test_continue_policy_skips_failed_statement(self):
        # WHENEVER SQLERROR CONTINUE in the statement list switches policy positionally.
        engine = _make_engine("oracle")
        engine._current_sqlplus_ctx = SqlplusContext()
        engine.provider.execute_statement.side_effect = [
            Exception("ORA-00942: table or view does not exist"),
            5,
        ]

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()
        result.has_error.return_value = False

        outcome = engine._execute_statements(
            ["WHENEVER SQLERROR CONTINUE", "DROP TABLE maybe_exists", "SELECT 5 FROM DUAL"],
            migration,
            result,
            0.0,
        )

        assert outcome is True
        assert engine.provider.execute_statement.call_count == 2
        engine.log.warning.assert_called()

    def test_exit_policy_stops_on_first_failure(self):
        # Default policy is "exit"; explicit WHENEVER SQLERROR EXIT also sets it.
        engine = _make_engine("oracle")
        engine._current_sqlplus_ctx = SqlplusContext()
        engine.provider.execute_statement.side_effect = Exception("ORA-00942")

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()
        result.has_error.return_value = False

        outcome = engine._execute_statements(
            ["WHENEVER SQLERROR EXIT", "DROP TABLE maybe_exists", "SELECT 5 FROM DUAL"],
            migration,
            result,
            0.0,
        )

        assert outcome is False
        assert engine.provider.execute_statement.call_count == 1

    def test_policy_switches_mid_script(self):
        # CONTINUE before critical section, EXIT after — each statement runs under its policy.
        engine = _make_engine("oracle")
        engine._current_sqlplus_ctx = SqlplusContext()
        engine.provider.execute_statement.side_effect = [
            Exception("ORA-00942"),  # cleanup DDL fails → CONTINUE skips
            0,  # main DDL succeeds
        ]

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()
        result.has_error.return_value = False

        outcome = engine._execute_statements(
            [
                "WHENEVER SQLERROR CONTINUE",
                "DROP TABLE maybe_exists",  # fails, skipped
                "WHENEVER SQLERROR EXIT",
                "CREATE TABLE t (id NUMBER)",  # succeeds
            ],
            migration,
            result,
            0.0,
        )

        assert outcome is True
        assert engine.provider.execute_statement.call_count == 2

    def test_infrastructure_error_not_swallowed_by_continue(self):
        # TransactionAbortedError must not be swallowed by WHENEVER SQLERROR CONTINUE;
        # only database-level SQL errors are skippable.
        engine = _make_engine("oracle")
        engine._current_sqlplus_ctx = SqlplusContext()
        engine.provider.execute_statement.side_effect = TransactionAbortedError("tx aborted")

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()
        result.has_error.return_value = False

        outcome = engine._execute_statements(
            ["WHENEVER SQLERROR CONTINUE", "DROP TABLE t"],
            migration,
            result,
            0.0,
        )

        assert outcome is False
        assert engine.provider.execute_statement.call_count == 1
        result.set_error.assert_called()

    def test_whenever_ignored_for_non_oracle_dialect(self):
        # For non-Oracle dialects, WHENEVER SQLERROR CONTINUE must not suppress errors.
        engine = _make_engine("postgresql")
        engine._current_sqlplus_ctx = None  # non-Oracle: no SqlplusContext
        engine.provider.execute_statement.side_effect = Exception("relation does not exist")

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()
        result.has_error.return_value = False

        outcome = engine._execute_statements(
            ["WHENEVER SQLERROR CONTINUE", "DROP TABLE t"],
            migration,
            result,
            0.0,
        )

        # WHENEVER SQLERROR CONTINUE is not processed for non-Oracle: statement fails normally.
        assert outcome is False
        assert engine.provider.execute_statement.call_count == 1


class TestDbmsOutputIntegration:
    def test_serveroutput_on_enables_dbms_output(self):
        engine = _make_engine("oracle")
        engine._current_sqlplus_ctx = SqlplusContext(serveroutput=True)
        conn = MagicMock()
        engine.provider.connection = conn
        engine.provider.execute_statement.return_value = 0

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()

        with (
            patch("dblift.db.plugins.oracle.oracle.dbms_output.enable_dbms_output") as mock_enable,
            patch("dblift.db.plugins.oracle.oracle.dbms_output.read_dbms_output") as mock_read,
        ):
            engine._execute_statements(["SELECT 1 FROM DUAL"], migration, result, 0.0)

        mock_enable.assert_called_once_with(conn)
        mock_read.assert_called_once_with(conn, engine.log)

    def test_serveroutput_off_does_not_enable(self):
        engine = _make_engine("oracle")
        engine._current_sqlplus_ctx = SqlplusContext(serveroutput=False)
        engine.provider.connection = MagicMock()
        engine.provider.execute_statement.return_value = 0

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()

        with patch("dblift.db.plugins.oracle.oracle.dbms_output.enable_dbms_output") as mock_enable:
            engine._execute_statements(["SELECT 1 FROM DUAL"], migration, result, 0.0)

        mock_enable.assert_not_called()

    def test_no_connection_skips_dbms_output(self):
        engine = _make_engine("oracle")
        engine._current_sqlplus_ctx = SqlplusContext(serveroutput=True)
        engine.provider.connection = None  # no connection
        engine.provider.execute_statement.return_value = 0

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()

        with patch("dblift.db.plugins.oracle.oracle.dbms_output.enable_dbms_output") as mock_enable:
            engine._execute_statements(["SELECT 1 FROM DUAL"], migration, result, 0.0)

        mock_enable.assert_not_called()
