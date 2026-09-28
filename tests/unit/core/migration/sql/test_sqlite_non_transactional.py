"""``PRAGMA foreign_keys`` must run outside any SQLite transaction.

SQLite's own reference states this plainly: "This pragma is a no-op within a
transaction; foreign key constraint enforcement may only be enabled or
disabled when there is no pending BEGIN" (pragma.html#pragma_foreign_keys).
Before this change, ``SqliteQuirks.non_transactional_sql_patterns`` was empty,
so a migration containing ``PRAGMA foreign_keys = OFF`` (or ``= ON``) was
wrapped in the same transaction as everything else and the pragma silently
did nothing -- FK enforcement stayed at whatever state it already had.
"""

from __future__ import annotations

import pytest

from dblift.core.migration.sql.execution_statement import classify_execution_statement

_NON_TRANSACTIONAL = [
    "PRAGMA foreign_keys = OFF",
    "PRAGMA foreign_keys = ON",
    "PRAGMA foreign_keys=OFF",
    "PRAGMA foreign_keys(1)",
    "PRAGMA foreign_keys(0)",
    "  pragma   foreign_keys  =  on  ",
    "PRAGMA FOREIGN_KEYS = 1;",
]

_TRANSACTIONAL = [
    "PRAGMA table_info(orders)",
    "PRAGMA foreign_key_check",
    "CREATE TABLE orders (id INTEGER PRIMARY KEY)",
    "INSERT INTO orders (id) VALUES (1)",
]


@pytest.mark.parametrize("sql", _NON_TRANSACTIONAL)
def test_pragma_foreign_keys_is_classified_non_transactional(sql):
    result = classify_execution_statement(sql, dialect="sqlite")
    assert result.can_execute_in_transaction is False
    assert result.transaction_reason


@pytest.mark.parametrize("sql", _TRANSACTIONAL)
def test_other_sqlite_statements_stay_transactional(sql):
    result = classify_execution_statement(sql, dialect="sqlite")
    assert result.can_execute_in_transaction is True, result.transaction_reason
