"""Transaction keywords use PostgreSQL's separators, not Python whitespace."""

import pytest

from dblift.core.migration.sql.execution_statement import classify_execution_statement


@pytest.mark.parametrize("dialect", ("postgresql", "timescaledb", "citus", "neon", "supabase"))
@pytest.mark.parametrize(
    "sql",
    (
        "CREATE INDEX CONCURRENTLY\u00a0ix ON t(a)",
        "CREATE\u00a0INDEX CONCURRENTLY ix ON t(a)",
        "VACUUM\u00a0t",
    ),
)
def test_non_ascii_name_character_does_not_separate_transaction_keywords(dialect, sql):
    assert classify_execution_statement(sql, dialect=dialect).can_execute_in_transaction


@pytest.mark.parametrize("dialect", ("postgresql", "timescaledb", "citus", "neon", "supabase"))
def test_ascii_blanks_still_separate_nontransactional_keywords(dialect):
    result = classify_execution_statement("CREATE INDEX CONCURRENTLY ix ON t(a)", dialect=dialect)
    assert not result.can_execute_in_transaction
