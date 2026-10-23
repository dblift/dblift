"""Snowflake transaction controls are refused before script execution in D1."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import TransactionStatementError
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.sql.execution_statement import neutralise_transaction_statements
from dblift.core.migration.sql.statement_reader import StatementReader
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.statement import execution_strings
from dblift.db.provider_registry import ProviderRegistry
from tests.unit._migration_factory import make_migration


def _prepared(script: str) -> list[str]:
    return execution_strings(StatementSplitter("snowflake").split(script))


@pytest.mark.parametrize(
    "script",
    [
        "BEGIN; SELECT 1; COMMIT;",
        "BEGIN WORK; SELECT 1; COMMIT;",
        "BEGIN TRANSACTION; SELECT 1; COMMIT;",
        "START TRANSACTION; SELECT 1; COMMIT;",
        "START TRANSACTION NAME 'migration'; SELECT 1; COMMIT;",
        "COMMIT;",
        "ROLLBACK;",
        "SELECT 0; COMMIT; SELECT 2;",
        "SELECT 0; ROLLBACK; SELECT 2;",
        "SELECT 0; BEGIN/* gap */WORK; SELECT 2;",
        "SELECT 0; START/* gap */TRANSACTION; SELECT 2;",
        "SELECT 0; COMMIT // comment\r; SELECT 2;",
        "SELECT 0; ROLLBACK -- comment\r; SELECT 2;",
    ],
)
def test_transaction_controls_are_refused_without_an_accepted_envelope(script: str) -> None:
    with pytest.raises(TransactionStatementError) as raised:
        neutralise_transaction_statements(
            _prepared(script),
            dialect="snowflake",
            log=MagicMock(),
            script_name="V1__x.sql",
            content=script,
        )

    assert "none of its statements were executed" in str(raised.value)
    assert "envelope" not in str(raised.value)
    assert "around its whole body is accepted" not in str(raised.value)


def test_snowflake_patterns_cannot_classify_a_transaction_envelope() -> None:
    patterns = ProviderRegistry.get_quirks("snowflake").transaction_control_sql_patterns

    assert patterns
    assert all(kind not in ("begin", "end") for _, kind in patterns)


def test_snowflake_comment_mask_uses_its_slash_and_cr_rules() -> None:
    quirks = ProviderRegistry.get_quirks("snowflake")

    assert quirks.blank_comments("BEGIN/* gap */WORK") == "BEGIN WORK"
    assert quirks.blank_comments("COMMIT // comment\r") == "COMMIT  \r"
    assert quirks.blank_comments("SELECT '// not a comment';") == "SELECT '// not a comment';"


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 'BEGIN; COMMIT'; SELECT 1 != 2;",
        "SELECT 'START TRANSACTION'; SELECT 1;",
        'SELECT 1 AS "ROLLBACK"; SELECT 2;',
        "SELECT 1 /* BEGIN; COMMIT */; SELECT 2;",
        "SELECT 1 // COMMIT;\r + 2; SELECT 3;",
    ],
)
def test_transaction_words_in_sql_quotes_and_comments_are_not_controls(script: str) -> None:
    statements = _prepared(script)

    assert (
        neutralise_transaction_statements(
            statements, dialect="snowflake", log=MagicMock(), content=script
        )
        == statements
    )


@pytest.mark.parametrize(
    "control",
    ["BEGIN", "BEGIN WORK", "BEGIN TRANSACTION", "START TRANSACTION", "COMMIT", "ROLLBACK"],
)
def test_execution_sends_zero_statements_when_a_control_is_present(control: str) -> None:
    provider = MagicMock()
    provider.execute_statement.return_value = 0
    log = MagicMock()
    engine = ExecutionEngine(provider, StatementReader(dialect="snowflake", logger=log), log)
    migration = make_migration(
        script_name="V1__x.sql",
        content=f"SELECT 0; {control}; SELECT 2;",
        logger=log,
        dialect="snowflake",
    )

    from dblift.core.logger.results import MigrateResult

    result = MigrateResult()
    engine.execute_migration(migration, result)

    assert provider.execute_statement.call_count == 0
    assert not result.success
    assert "manages the transaction" in result.error_message


@pytest.mark.parametrize("dialect", ["sqlite", "duckdb"])
def test_existing_transaction_refusal_message_is_byte_identical(dialect: str) -> None:
    with pytest.raises(TransactionStatementError) as raised:
        neutralise_transaction_statements(
            ["SELECT 0", "COMMIT"],
            dialect=dialect,
            log=MagicMock(),
            script_name="V1__x.sql",
            content="SELECT 0; COMMIT;",
        )

    assert str(raised.value) == (
        "V1__x.sql, line 1: COMMIT manages the transaction, which dblift already opens "
        "for each script, so none of its statements were executed. Remove it; a script "
        "that is only BEGIN ... COMMIT around its whole body is accepted."
    )
