"""Characterization of ``neutralise_transaction_statements`` branches no other suite exercises.

A dialect without ``transaction_control_sql_patterns`` still refuses a psql combined execution unit
(``a \\; b``) that holds a transaction statement. These cases pin how the scan treats a combined
unit with a single constituent and how it carries on past a combined unit that holds none.
"""

from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import TransactionStatementError
from dblift.core.migration.sql.execution_statement import neutralise_transaction_statements
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.statement import execution_strings


def _neutralise(content):
    records = StatementSplitter("postgresql").split(content)
    statements = execution_strings(records)
    log = MagicMock()
    out = neutralise_transaction_statements(
        statements,
        dialect="postgresql",
        log=log,
        script_name="V1__x.sql",
        content=content,
        records=records,
    )
    return statements, out, log


@pytest.mark.parametrize("content", ["BEGIN \\;", "COMMIT \\;", "\\; COMMIT;"])
def test_a_combined_unit_with_one_constituent_is_not_scanned_for_transaction_control(content):
    statements, out, log = _neutralise(content)

    assert list(out) == statements
    assert out.policy_texts == [None]
    assert log.mock_calls == []


def test_the_scan_carries_on_past_a_combined_unit_without_transaction_control():
    with pytest.raises(TransactionStatementError) as refusal:
        _neutralise("SELECT 1 \\; SELECT 2;\nSELECT 3 \\; COMMIT;")

    assert str(refusal.value) == (
        "V1__x.sql, line 2: COMMIT manages the transaction inside one execution unit, so none "
        "of its statements were executed. Remove it from the combined unit."
    )
