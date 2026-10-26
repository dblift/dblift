"""Preflight must use the execution scanner's supplied record expansion."""

from dataclasses import replace

import pytest

from dblift.core.exceptions import TransactionStatementError
from dblift.core.logger import NullLog
from dblift.core.migration.sql.execution_statement import neutralise_transaction_statements
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.statement import execution_strings


def test_supplied_records_must_expand_to_the_execution_strings() -> None:
    script = "SELECT 1; COMMIT;"
    splitter = StatementSplitter("postgresql")
    records = splitter.split(script)
    with pytest.raises(TransactionStatementError, match="scanner records"):
        neutralise_transaction_statements(
            ["SELECT 1"],
            dialect="postgresql",
            log=NullLog(),
            content=script,
            records=records,
            record_policy_texts=splitter.last_policy_texts(script),
        )


def test_repeat_and_skip_records_align_without_a_second_split() -> None:
    script = "SELECT 1;\nGO 0\nSELECT 2;\nGO 2\n"
    splitter = StatementSplitter("sqlserver")
    records = splitter.split(script)
    sent = execution_strings(records)

    assert sent == ["SELECT 2;", "SELECT 2;"]
    assert (
        neutralise_transaction_statements(
            sent,
            dialect="sqlserver",
            log=NullLog(),
            content=script,
            records=records,
            record_policy_texts=splitter.last_policy_texts(script),
        )
        == sent
    )


def test_refusal_uses_supplied_record_line_without_rescanning() -> None:
    script = "SELECT 1;\nCOMMIT;"
    splitter = StatementSplitter("sqlite")
    records = splitter.split(script)
    records[-1] = replace(records[-1], line=73)
    with pytest.raises(TransactionStatementError, match=r"line 73: COMMIT manages"):
        neutralise_transaction_statements(
            execution_strings(records),
            dialect="sqlite",
            log=NullLog(),
            content=script,
            records=records,
            record_policy_texts=splitter.last_policy_texts(script),
        )


@pytest.mark.parametrize("policy_texts", [[], [None, None]])
def test_supplied_policy_views_must_align_with_records(policy_texts) -> None:
    script = "SELECT 1;"
    records = StatementSplitter("sqlite").split(script)
    with pytest.raises(TransactionStatementError, match="scanner policy views"):
        neutralise_transaction_statements(
            execution_strings(records),
            dialect="sqlite",
            log=NullLog(),
            content=script,
            records=records,
            record_policy_texts=policy_texts,
        )
