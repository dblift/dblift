"""Preflight must use the execution scanner's supplied record expansion."""

from unittest.mock import patch

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
    script = "SELECT 1;\n\nCOMMIT;"
    splitter = StatementSplitter("sqlite")
    records = splitter.split(script)
    with patch(
        "dblift.core.migration.sql.execution_statement._script_parser",
        side_effect=AssertionError("the script was split twice"),
    ):
        with pytest.raises(TransactionStatementError, match=r"line 3: COMMIT manages"):
            neutralise_transaction_statements(
                execution_strings(records),
                dialect="sqlite",
                log=NullLog(),
                content=script,
                records=records,
                record_policy_texts=splitter.last_policy_texts(script),
            )
