"""``neutralise_transaction_statements`` and the ``transaction_control_sql_patterns`` quirk.

dblift runs a migration in one transaction of its own. On SQLite and DuckDB a script that is
exactly ``BEGIN; ...; COMMIT;`` is that transaction, so the envelope is dropped with a warning;
any other BEGIN/COMMIT/END/ROLLBACK/ABORT is refused before anything runs. Snowflake refuses
all matched transaction controls; the remaining dialects keep an empty table.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import TransactionStatementError, UnsupportedMetaCommandError
from dblift.core.migration.sql.execution_statement import neutralise_transaction_statements
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.db.base_quirks import BaseQuirks
from dblift.db.provider_registry import ProviderRegistry

BODY = ["CREATE TABLE t (a INT)", "INSERT INTO t VALUES (1)"]


def _run(statements, dialect="sqlite", content="", name="V1__x.sql"):
    log = MagicMock()
    out = neutralise_transaction_statements(
        statements, dialect=dialect, log=log, script_name=name, content=content
    )
    return out, log


def _kinds(dialect, text):
    """The kind the function would give *text*: the first pattern that matches, as a list."""
    patterns = ProviderRegistry.get_quirks(dialect).transaction_control_sql_patterns
    return [kind for pattern, kind in patterns if re.match(pattern, text)][:1]


def test_base_quirks_default_is_empty():
    assert BaseQuirks.transaction_control_sql_patterns == ()


@pytest.mark.parametrize(
    "text, kind",
    [
        ("BEGIN", "begin"),
        ("BEGIN;", "begin"),
        ("BEGIN TRANSACTION", "begin"),
        ("BEGIN DEFERRED", "begin"),
        ("BEGIN IMMEDIATE TRANSACTION;", "begin"),
        ("COMMIT", "end"),
        ("COMMIT TRANSACTION;", "end"),
        ("END", "end"),
        ("END TRANSACTION", "end"),
        ("ROLLBACK", "abort"),
        ("ROLLBACK TRANSACTION;", "abort"),
        ("BEGIN EXCLUSIVE", "begin_other"),
        ("BEGIN EXCLUSIVE TRANSACTION", "begin_other"),
    ],
)
def test_sqlite_patterns_match(text, kind):
    assert _kinds("sqlite", text) == [kind]


@pytest.mark.parametrize(
    "text",
    [
        "ROLLBACK TO s",
        "ROLLBACK TRANSACTION TO SAVEPOINT s",
        "SAVEPOINT s",
        "RELEASE s",
        "START TRANSACTION",
        "ABORT",
        "COMMIT WORK",
        "BEGIN_LOG",
        "CREATE TABLE begin_log (a INT)",
        "INSERT INTO t VALUES (1)",
        "CREATE TRIGGER tg AFTER INSERT ON t BEGIN SELECT 1; END",
        "COMMITTED",
    ],
)
def test_sqlite_patterns_do_not_match(text):
    assert _kinds("sqlite", text) == []


@pytest.mark.parametrize(
    "text, kind",
    [
        ("BEGIN", "begin"),
        ("BEGIN TRANSACTION;", "begin"),
        ("START TRANSACTION", "begin"),
        ("COMMIT", "end"),
        ("END TRANSACTION", "end"),
        ("ROLLBACK", "abort"),
        ("ABORT;", "abort"),
        ("ABORT TRANSACTION", "abort"),
        ("BEGIN WORK", "begin"),
        ("START TRANSACTION", "begin"),
        ("COMMIT WORK;", "end"),
        ("END WORK", "end"),
        ("ROLLBACK WORK", "abort"),
        ("ABORT WORK;", "abort"),
        ("BEGIN TRANSACTION READ ONLY", "begin_other"),
        ("START TRANSACTION READ ONLY", "begin_other"),
    ],
)
def test_duckdb_patterns_match(text, kind):
    assert _kinds("duckdb", text) == [kind]


@pytest.mark.parametrize(
    "text",
    [
        "START",
        "ROLLBACK TO s",
        "SAVEPOINT s",
        "BEGIN_LOG",
        "CREATE TABLE t (a INT)",
    ],
)
def test_duckdb_patterns_do_not_match(text):
    assert _kinds("duckdb", text) == []


@pytest.mark.parametrize("dialect", ["sqlite", "duckdb"])
class TestEnvelope:
    def test_begin_first_and_commit_last_are_dropped_with_a_warning(self, dialect):
        out, log = _run(["BEGIN;", *BODY, "COMMIT;"], dialect)
        assert out == BODY
        log.warning.assert_called_once_with(
            "Dropped BEGIN and COMMIT from V1__x.sql: dblift runs the script in one "
            "transaction of its own"
        )

    def test_the_warning_names_the_statements_as_written(self, dialect):
        out, log = _run(["begin transaction", *BODY, "end transaction;"], dialect)
        assert out == BODY
        assert "Dropped BEGIN TRANSACTION and END TRANSACTION from" in log.warning.call_args.args[0]

    def test_comments_around_the_envelope_are_not_statements(self, dialect):
        script = "-- header\nBEGIN;\n-- note\nCREATE TABLE t (a INT);\nINSERT INTO t VALUES (1);\nCOMMIT;\n-- done\n"
        statements = StatementSplitter(dialect).split_statements(script)
        assert len(statements) == 4  # the comments are no statements
        out, _ = _run(statements, dialect, content=script)
        assert out == statements[1:-1]

    def test_a_leading_comment_on_the_statement_itself(self, dialect):
        out, _ = _run(["-- hi\nBEGIN", *BODY, "/* x */ COMMIT"], dialect)
        assert out == BODY

    def test_empty_envelope_is_dropped(self, dialect):
        out, _ = _run(["BEGIN", "COMMIT"], dialect)
        assert out == []

    @pytest.mark.parametrize(
        "statements, offender",
        [
            (["COMMIT"], "COMMIT"),
            ([*BODY, "COMMIT"], "COMMIT"),
            (["BEGIN", *BODY], "BEGIN"),
            ([BODY[0], "BEGIN", BODY[1], "COMMIT"], "BEGIN"),
            (["BEGIN", BODY[0], "COMMIT", BODY[1]], "COMMIT"),
            ([BODY[0], "END", BODY[1]], "END"),
            ([BODY[0], "ROLLBACK", BODY[1]], "ROLLBACK"),
            (["BEGIN", BODY[0], "ROLLBACK"], "ROLLBACK"),
            (["BEGIN", BODY[0], "COMMIT", "BEGIN", BODY[1], "COMMIT"], "COMMIT"),
            (["BEGIN", "BEGIN", BODY[0], "COMMIT"], "BEGIN"),
            (["BEGIN", BODY[0], "COMMIT", "COMMIT"], "COMMIT"),
        ],
    )
    def test_anything_else_is_refused_naming_the_statement(self, dialect, statements, offender):
        with pytest.raises(UnsupportedMetaCommandError) as raised:
            _run(statements, dialect)
        message = str(raised.value)
        assert "V1__x.sql" in message
        assert f"{offender} manages the transaction" in message
        assert "none of its statements were executed" in message

    def test_a_comment_between_the_keyword_and_the_semicolon_is_not_part_of_the_statement(
        self, dialect
    ):
        out, _ = _run(["BEGIN /* a */", *BODY, "COMMIT -- b\n"], dialect)
        assert out == BODY
        with pytest.raises(TransactionStatementError, match="COMMIT manages"):
            _run([BODY[0], "COMMIT /* c */", BODY[1]], dialect)

    def test_a_word_inside_a_comment_or_string_is_not_a_statement(self, dialect):
        statements = ["/* COMMIT */ SELECT 'COMMIT'", "-- ROLLBACK\nSELECT 1"]
        assert _run(statements, dialect)[0] is statements

    def test_refusal_is_a_transaction_statement_error(self, dialect):
        with pytest.raises(TransactionStatementError) as raised:
            _run(["COMMIT"], dialect)
        assert isinstance(raised.value, UnsupportedMetaCommandError)

    def test_savepoints_run_as_written(self, dialect):
        statements = ["BEGIN", "SAVEPOINT s", BODY[1], "ROLLBACK TO s", "RELEASE s", "COMMIT"]
        out, _ = _run(statements, dialect)
        assert out == ["SAVEPOINT s", BODY[1], "ROLLBACK TO s", "RELEASE s"]

    def test_a_script_without_transaction_statements_is_returned_untouched(self, dialect):
        statements = [*BODY, "SAVEPOINT s"]
        out, log = _run(statements, dialect)
        assert out is statements
        log.warning.assert_not_called()


@pytest.mark.parametrize(
    "dialect, statement, reason",
    [
        ("sqlite", "VACUUM", "VACUUM cannot run inside a transaction"),
        (
            "duckdb",
            "CHECKPOINT",
            "DuckDB CHECKPOINT cannot run in a transaction with local changes",
        ),
        (
            "duckdb",
            "FORCE CHECKPOINT",
            "DuckDB CHECKPOINT cannot run in a transaction with local changes",
        ),
    ],
)
def test_envelope_policy_refuses_statements_that_can_fail_in_a_transaction(
    dialect, statement, reason
):
    with pytest.raises(TransactionStatementError) as raised:
        _run(["BEGIN", statement, "COMMIT"], dialect)
    assert f"{statement} cannot stay inside the envelope" in str(raised.value)
    assert reason in str(raised.value)


@pytest.mark.parametrize("statement", ["CHECKPOINT", "FORCE CHECKPOINT"])
def test_duckdb_checkpoint_succeeds_clean_and_fails_with_local_changes(statement):
    duckdb = pytest.importorskip("duckdb")
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TABLE t (a INT)")
        connection.execute(statement)
        connection.execute("BEGIN")
        connection.execute(statement)
        connection.execute("COMMIT")
        connection.execute("BEGIN")
        connection.execute("INSERT INTO t VALUES (1)")
        with pytest.raises(duckdb.TransactionException):
            connection.execute(statement)


def _split(dialect, content):
    from dblift.core.migration.sql.statement_reader import StatementReader

    return StatementReader(dialect=dialect, logger=MagicMock()).split_statements(content)


@pytest.mark.parametrize("dialect", ["sqlite", "duckdb"])
def test_refusal_names_the_line_of_the_statement_in_the_script(dialect):
    content = "CREATE TABLE t (a INT);\n\n-- x\nROLLBACK;\nCREATE TABLE u (a INT);\n"
    with pytest.raises(TransactionStatementError, match=r"V1__x\.sql, line 4: ROLLBACK manages"):
        _run(_split(dialect, content), dialect, content=content)


def test_refusal_falls_back_to_the_statement_number_when_the_line_is_unknown():
    with pytest.raises(
        UnsupportedMetaCommandError, match=r"V1__x\.sql, statement 2: COMMIT manages"
    ):
        _run([BODY[0], "COMMIT"], content="no match here")


def _registered_dialects():
    return sorted({plugin.name for plugin in ProviderRegistry.list_plugins()})


def test_remaining_dialects_without_patterns_are_untouched():
    others = [d for d in _registered_dialects() if d not in ("sqlite", "duckdb", "snowflake")]
    assert {"postgresql", "mysql", "oracle", "sqlserver"} <= set(others)
    statements = ["BEGIN", *BODY, "COMMIT", "ROLLBACK", "END"]
    for dialect in others:
        assert ProviderRegistry.get_quirks(dialect).transaction_control_sql_patterns == (), dialect
        out, log = _run(statements, dialect)
        assert out is statements, dialect
        log.warning.assert_not_called()


@pytest.mark.parametrize(
    "dialect, begin, end",
    [("duckdb", "BEGIN WORK", "COMMIT WORK"), ("duckdb", "START TRANSACTION", "END WORK")],
)
def test_duckdb_work_spellings_form_an_envelope(dialect, begin, end):
    out, _ = _run([begin, *BODY, end], dialect)
    assert out == BODY


@pytest.mark.parametrize(
    "word", ["COMMIT WORK", "END WORK", "ROLLBACK WORK", "ABORT WORK", "BEGIN WORK"]
)
def test_duckdb_work_spellings_are_refused_mid_script(word):
    with pytest.raises(TransactionStatementError, match=f"{word} manages the transaction"):
        _run([BODY[0], word, BODY[1]], "duckdb")


@pytest.mark.parametrize(
    "dialect, begin", [("sqlite", "BEGIN EXCLUSIVE"), ("duckdb", "BEGIN TRANSACTION READ ONLY")]
)
def test_a_begin_with_options_is_named_as_the_cause(dialect, begin):
    with pytest.raises(TransactionStatementError) as raised:
        _run([begin, *BODY, "COMMIT"], dialect)
    assert f"{begin} cannot stand in for dblift's transaction" in str(raised.value)
    assert "only a plain BEGIN" in str(raised.value)


@pytest.mark.parametrize("dialect", ["sqlite", "duckdb"])
def test_refusal_line_ignores_the_same_word_in_comments(dialect):
    content = "CREATE TABLE t(a INT);\n-- remember COMMIT;\nINSERT INTO t VALUES(1); -- COMMIT;\nCOMMIT;\n"
    with pytest.raises(TransactionStatementError, match=r"V1__x\.sql, line 4: COMMIT manages"):
        _run(_split(dialect, content), dialect, content=content)


@pytest.mark.parametrize(
    "dialect, begin", [("sqlite", "BEGIN EXCLUSIVE"), ("duckdb", "BEGIN TRANSACTION READ ONLY")]
)
def test_a_begin_with_options_mid_script_gets_the_ordinary_refusal(dialect, begin):
    with pytest.raises(TransactionStatementError) as raised:
        _run([BODY[0], begin, BODY[1], "COMMIT"], dialect)
    assert f"{begin} manages the transaction" in str(raised.value)
    assert "only a plain BEGIN" not in str(raised.value)


def test_the_envelope_refusal_names_the_reason_once():
    with pytest.raises(TransactionStatementError) as raised:
        _run(["BEGIN", "VACUUM", "COMMIT"], "sqlite")
    assert str(raised.value).count("cannot run inside a transaction") == 1
