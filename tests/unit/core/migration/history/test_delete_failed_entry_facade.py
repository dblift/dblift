"""``MigrationHistoryManager.delete_failed_migration_entry`` behaviour.

The facade turns a row count into a verdict for ``repair``. Two things are
easy to get wrong and were previously only asserted indirectly:

* the *normalized* history-table name must reach the provider (ADR-0015 —
  Oracle folds unquoted identifiers to uppercase),
* a driver that reports an unknown row count of ``-1`` for DML (duckdb
  among them) must trigger a re-read rather than be read as "nothing
  removed".
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager


def _manager(rows_deleted, *, remaining=None, dialect="postgresql", false_literal="FALSE"):
    provider = MagicMock()
    provider.delete_failed_migration_entry.return_value = rows_deleted
    provider.get_normalized_object_name.side_effect = lambda name: name
    provider.get_schema_qualified_name.side_effect = lambda s, t: f'"{s}"."{t}"'
    provider.quirks = SimpleNamespace(boolean_false_literal=false_literal)
    provider.execute_query.return_value = remaining if remaining is not None else []
    manager = MigrationHistoryManager(
        provider=provider, schema="public", installed_by="tester", logger=MagicMock()
    )
    return manager, provider


def test_reports_removal_when_a_row_was_deleted():
    manager, provider = _manager(1)

    assert manager.delete_failed_migration_entry("V1__x.sql") is True
    provider.delete_failed_migration_entry.assert_called_once_with(
        "public", "V1__x.sql", "dblift_schema_history"
    )
    provider.execute_query.assert_not_called()


def test_reports_nothing_removed_when_no_row_matched():
    manager, provider = _manager(0)

    assert manager.delete_failed_migration_entry("V1__x.sql") is False
    provider.execute_query.assert_not_called()


def test_passes_the_normalized_table_name():
    """Oracle stores the history table upper-cased; the facade must forward that."""
    manager, provider = _manager(1)
    provider.get_normalized_object_name.side_effect = lambda name: name.upper()

    manager.delete_failed_migration_entry("V1__x.sql")

    assert provider.delete_failed_migration_entry.call_args.args[2] == "DBLIFT_SCHEMA_HISTORY"


def test_unknown_rowcount_rereads_and_confirms_removal():
    """duckdb-style ``-1``: the row is gone, so the verdict is True."""
    manager, provider = _manager(-1, remaining=[])

    assert manager.delete_failed_migration_entry("V1__x.sql") is True

    sql, params = provider.execute_query.call_args.args
    assert "SELECT 1 FROM" in sql
    assert "success = FALSE" in sql
    assert params == ["V1__x.sql"]


def test_unknown_rowcount_reports_failure_when_the_row_survives():
    manager, _provider = _manager(-1, remaining=[{"1": 1}])

    assert manager.delete_failed_migration_entry("V1__x.sql") is False


def test_reread_uses_the_dialect_false_literal():
    """Oracle stores ``success`` as NUMBER(1) — the predicate must read ``0``."""
    manager, provider = _manager(-1, remaining=[], dialect="oracle", false_literal="0")

    manager.delete_failed_migration_entry("V1__x.sql")

    sql = provider.execute_query.call_args.args[0]
    assert "success = 0" in sql
    assert "FALSE" not in sql


def test_unknown_rowcount_on_a_provider_without_read_access_assumes_removal():
    """No ``execute_query`` to verify with: don't claim the row survived."""
    provider = MagicMock(spec=["delete_failed_migration_entry", "get_normalized_object_name"])
    provider.delete_failed_migration_entry.return_value = -1
    provider.get_normalized_object_name.side_effect = lambda name: name
    manager = MigrationHistoryManager(
        provider=provider, schema="public", installed_by="tester", logger=MagicMock()
    )

    assert manager.delete_failed_migration_entry("V1__x.sql") is True


@pytest.mark.parametrize("rows", [2, 5])
def test_multiple_rows_removed_still_reads_as_success(rows):
    manager, _provider = _manager(rows)

    assert manager.delete_failed_migration_entry("V1__x.sql") is True
