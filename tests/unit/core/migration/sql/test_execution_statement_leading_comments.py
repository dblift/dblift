"""A comment in front of an autocommit-only statement must not hide it."""

import pytest

from dblift.core.migration.sql.execution_statement import classify_execution_statement


@pytest.mark.unit
@pytest.mark.parametrize(
    "dialect, sql",
    [
        ("postgresql", "-- build the index online\nCREATE INDEX CONCURRENTLY ix ON t (a)"),
        ("postgresql", "/* online */ CREATE INDEX CONCURRENTLY ix ON t (a)"),
        ("postgresql", "-- one\n-- two\n\n/* three */\nCREATE INDEX CONCURRENTLY ix ON t (a)"),
        ("sqlite", "-- Schema synchronization\n\nPRAGMA foreign_keys = OFF"),
    ],
)
def test_leading_comments_do_not_hide_a_non_transactional_statement(dialect, sql):
    classified = classify_execution_statement(sql, dialect=dialect)

    assert classified.can_execute_in_transaction is False
    assert classified.transaction_reason
    assert classified.sql == sql


@pytest.mark.unit
def test_a_comment_mentioning_the_keyword_does_not_mark_a_transactional_statement():
    sql = "-- was CREATE INDEX CONCURRENTLY before\nCREATE INDEX ix ON t (a)"

    assert classify_execution_statement(sql, dialect="postgresql").can_execute_in_transaction
