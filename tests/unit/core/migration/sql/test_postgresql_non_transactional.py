"""Statements PostgreSQL refuses inside a transaction block.

``classify_execution_statement`` decides whether the execution engine may wrap
a statement in a transaction. When it says yes and the server says no, the
statement fails at apply time against a real database -- after the rest of the
transaction has already been rolled back, which is the worst place to find out.

The list it consults (``quirks.non_transactional_sql_patterns``) covered the
CONCURRENTLY family, VACUUM, REINDEX DATABASE and REINDEX SYSTEM, and missed
several commands whose own reference pages state the same restriction in as
many words. Each case below quotes the sentence it rests on, so a reader can
check the claim rather than trust the list.
"""

from __future__ import annotations

import pytest

from core.migration.sql.execution_statement import classify_execution_statement

# (statement, the documented sentence that puts it here)
_NON_TRANSACTIONAL = [
    (
        "REINDEX SCHEMA app",
        'sql-reindex.html: "This form of REINDEX cannot be executed inside a '
        'transaction block."',
    ),
    (
        "CLUSTER",
        'sql-cluster.html: "This form of CLUSTER cannot be executed inside a '
        'transaction block."',
    ),
    (
        "CREATE DATABASE analytics",
        'sql-createdatabase.html: "CREATE DATABASE cannot be executed inside a '
        'transaction block."',
    ),
    (
        "DROP DATABASE analytics",
        'sql-dropdatabase.html: "DROP DATABASE cannot be executed inside a ' 'transaction block."',
    ),
    (
        "CREATE TABLESPACE fast LOCATION '/mnt/fast'",
        'sql-createtablespace.html: "CREATE TABLESPACE cannot be executed inside '
        'a transaction block."',
    ),
    (
        "DROP TABLESPACE fast",
        'sql-droptablespace.html: "DROP TABLESPACE cannot be executed inside a '
        'transaction block."',
    ),
    (
        "ALTER SYSTEM SET work_mem = '64MB'",
        'sql-altersystem.html: "since this command acts directly on the file '
        "system and cannot be rolled back, it is not allowed inside a "
        'transaction block or function."',
    ),
]

# Already covered before this change; kept so a regression in either direction
# is visible.
_ALREADY_COVERED = [
    "CREATE INDEX CONCURRENTLY ix ON orders (email)",
    "CREATE UNIQUE INDEX CONCURRENTLY ix ON orders (email)",
    "DROP INDEX CONCURRENTLY ix",
    "REINDEX TABLE CONCURRENTLY orders",
    "REINDEX INDEX CONCURRENTLY ix",
    "REINDEX DATABASE mydb",
    "REINDEX SYSTEM mydb",
    "VACUUM orders",
]

# These CAN run inside a transaction, and must keep doing so. Wrapping is the
# default and the safer behaviour: it is what makes a failed migration roll
# back, so a false positive here costs more than a missing entry.
_TRANSACTIONAL = [
    "REINDEX TABLE orders",
    "REINDEX INDEX ix",
    "CLUSTER orders USING ix",
    "CREATE INDEX ix ON orders (email)",
    "DROP INDEX ix",
    "CREATE TABLE orders (id int)",
    "ALTER TABLE orders ADD COLUMN note text",
    "INSERT INTO orders (id) VALUES (1)",
    "ALTER TABLE orders SET TABLESPACE fast",
]


@pytest.mark.parametrize("sql,citation", _NON_TRANSACTIONAL, ids=[c[0] for c in _NON_TRANSACTIONAL])
def test_a_documented_non_transactional_statement_is_classified_as_such(sql, citation):
    result = classify_execution_statement(sql, dialect="postgresql")
    assert result.can_execute_in_transaction is False, citation
    assert result.transaction_reason, "a refusal with no reason is not actionable"


@pytest.mark.parametrize("sql", _ALREADY_COVERED)
def test_the_previously_covered_statements_stay_covered(sql):
    assert (
        classify_execution_statement(sql, dialect="postgresql").can_execute_in_transaction is False
    )


@pytest.mark.parametrize("sql", _TRANSACTIONAL)
def test_an_ordinary_statement_may_still_be_wrapped(sql):
    result = classify_execution_statement(sql, dialect="postgresql")
    assert result.can_execute_in_transaction is True, result.transaction_reason


def test_the_table_scoped_spellings_are_not_swept_up_with_the_broad_ones():
    # CLUSTER <table> USING <index> and REINDEX TABLE are transactional; only
    # the forms that name no single object are not. A pattern anchored on the
    # bare verb would catch both.
    assert (
        classify_execution_statement(
            "CLUSTER orders USING ix", dialect="postgresql"
        ).can_execute_in_transaction
        is True
    )
    assert (
        classify_execution_statement("CLUSTER", dialect="postgresql").can_execute_in_transaction
        is False
    )


def test_classification_is_case_and_whitespace_insensitive():
    for sql in ("  cluster  ", "Cluster", "CLUSTER;", "  reindex   schema   app  "):
        assert (
            classify_execution_statement(sql, dialect="postgresql").can_execute_in_transaction
            is False
        ), sql
