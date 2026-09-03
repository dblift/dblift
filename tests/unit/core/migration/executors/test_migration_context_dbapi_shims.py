"""BUG-01 regression: ``MigrationContext`` must be DBAPI-compatible.

Classic Python migration idioms (Flyway-style, SQLAlchemy tutorials, plain
DBAPI) expect ``conn.cursor().execute(sql)`` and ``conn.commit()``. Without
those shims, scripts written against that idiom exploded with
``AttributeError: 'MigrationContext' object has no attribute 'cursor'``,
even though dblift's ExecutionEngine already owns the transaction.

The fix adds ``cursor()`` (returns self), ``commit()`` (no-op) and
``rollback()`` (no-op) to MigrationContext. ``execute()`` remains the
documented path; these three are compatibility shims only.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.executors.python_executor import MigrationContext


@pytest.mark.unit
class TestMigrationContextDbapiShims:
    def _ctx(self) -> MigrationContext:
        return MigrationContext(provider=MagicMock(), log=MagicMock(), dry_run=False)

    def test_cursor_returns_self(self):
        ctx = self._ctx()
        assert ctx.cursor() is ctx

    def test_cursor_execute_forwards_to_provider(self):
        ctx = self._ctx()
        ctx.cursor().execute("CREATE TABLE t (id INT)")
        ctx.provider.execute_statement.assert_called_once_with("CREATE TABLE t (id INT)")

    def test_commit_is_noop(self):
        ctx = self._ctx()
        assert ctx.commit() is None
        ctx.provider.execute_statement.assert_not_called()

    def test_rollback_is_noop(self):
        ctx = self._ctx()
        assert ctx.rollback() is None
        ctx.provider.execute_statement.assert_not_called()

    def test_dbapi_chain_idiom_works(self):
        """The canonical ``conn.cursor().execute(...); conn.commit()`` flow."""
        ctx = self._ctx()
        cur = ctx.cursor()
        cur.execute("INSERT INTO t VALUES (1)")
        ctx.commit()
        ctx.provider.execute_statement.assert_called_once_with("INSERT INTO t VALUES (1)")
