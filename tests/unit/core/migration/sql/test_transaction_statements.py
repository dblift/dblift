"""``neutralise_transaction_statements`` and the ``transaction_control_sql_patterns`` quirk.

dblift runs a migration in one transaction of its own. On SQLite and DuckDB a script that is
exactly ``BEGIN; ...; COMMIT;`` is that transaction, so the envelope is dropped with a warning;
any other BEGIN/COMMIT/END/ROLLBACK/ABORT is refused before anything runs. Every other dialect
keeps an empty table and is returned untouched.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import UnsupportedMetaCommandError
from dblift.core.migration.sql.execution_statement import neutralise_transaction_statements
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
    return [
        kind
        for pattern, kind in ProviderRegistry.get_quirks(dialect).transaction_control_sql_patterns
        if __import__("re").match(pattern, text)
    ]


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
        "BEGIN EXCLUSIVE",
        "START TRANSACTION",
        "ABORT",
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
        "BEGIN TRANSACTION READ ONLY",
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
            "Dropped BEGIN and COMMIT from V1__x.sql: dblift runs the migration in one "
            "transaction of its own"
        )

    def test_the_warning_names_the_statements_as_written(self, dialect):
        out, log = _run(["begin transaction", *BODY, "end transaction;"], dialect)
        assert out == BODY
        assert "Dropped BEGIN TRANSACTION and END TRANSACTION from" in log.warning.call_args.args[0]

    def test_comments_around_the_envelope_are_not_statements(self, dialect):
        statements = ["-- header", "BEGIN", "-- note", *BODY, "COMMIT", "-- done"]
        out, _ = _run(statements, dialect)
        assert out == ["-- header", "-- note", *BODY, "-- done"]

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

    def test_savepoints_run_as_written(self, dialect):
        statements = ["BEGIN", "SAVEPOINT s", BODY[1], "ROLLBACK TO s", "RELEASE s", "COMMIT"]
        out, _ = _run(statements, dialect)
        assert out == ["SAVEPOINT s", BODY[1], "ROLLBACK TO s", "RELEASE s"]

    def test_a_script_without_transaction_statements_is_returned_untouched(self, dialect):
        statements = [*BODY, "SAVEPOINT s"]
        out, log = _run(statements, dialect)
        assert out is statements
        log.warning.assert_not_called()


def test_refusal_names_the_line_of_the_statement_in_the_script():
    content = "CREATE TABLE t (a INT);\n\n-- x\nROLLBACK;\nCREATE TABLE u (a INT);\n"
    statements = ["CREATE TABLE t (a INT);", "-- x\nROLLBACK;", "CREATE TABLE u (a INT);"]
    with pytest.raises(UnsupportedMetaCommandError, match=r"V1__x\.sql, line 4: ROLLBACK manages"):
        _run(statements, content=content)


def test_refusal_falls_back_to_the_statement_number_when_the_line_is_unknown():
    with pytest.raises(
        UnsupportedMetaCommandError, match=r"V1__x\.sql, statement 2: COMMIT manages"
    ):
        _run([BODY[0], "COMMIT"], content="no match here")


def _registered_dialects():
    return sorted({plugin.name for plugin in ProviderRegistry.list_plugins()})


def test_every_other_dialect_has_no_patterns_and_is_untouched():
    others = [d for d in _registered_dialects() if d not in ("sqlite", "duckdb")]
    assert {"postgresql", "mysql", "oracle", "sqlserver"} <= set(others)
    statements = ["BEGIN", *BODY, "COMMIT", "ROLLBACK", "END"]
    for dialect in others:
        assert ProviderRegistry.get_quirks(dialect).transaction_control_sql_patterns == (), dialect
        out, log = _run(statements, dialect)
        assert out is statements, dialect
        log.warning.assert_not_called()
