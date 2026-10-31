"""``_prepare_transaction`` on a caller-owned connection must not leave a stale schema cache.

``DBLiftClient.from_sqlalchemy(connection=...)`` binds the caller's connection
to the provider and never commits on it. ``_apply_configured_schema()`` then
issues ``SET search_path`` inside SQLAlchemy's implicit transaction, and the
defensive rollback at the start of ``_prepare_transaction`` undoes it, with
``provider._tx`` still ``None``. The migration's statements must re-apply the
schema rather than run on the server default.
"""

from unittest.mock import MagicMock, patch

from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.formats import MigrationFormat
from dblift.core.migration.migration import Migration
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider


class _FakeConnection:
    closed = False

    def __init__(self) -> None:
        self.open = True

    def in_transaction(self) -> bool:
        return self.open

    def rollback(self) -> None:
        self.open = False


class _Provider(PostgreSqlProvider):
    def __init__(self) -> None:
        self._tx = None  # nothing explicit: the connection autobegan on the SET
        self._connection = _FakeConnection()
        self._external_connection = True
        self._schema_applied_for = "app"  # _apply_configured_schema() already ran


def test_prepare_transaction_on_external_connection_invalidates_schema_cache():
    provider = _Provider()
    engine = ExecutionEngine(
        provider=provider, sql_analyzer=MagicMock(), log=MagicMock(), config=None
    )
    migration = MagicMock(spec=Migration)
    migration.format = MigrationFormat.SQL
    migration.script_name = "V1__init.sql"

    with patch.object(SqlAlchemyProvider, "begin_transaction", lambda self: None):
        started = engine._prepare_transaction(migration)

    assert started
    assert provider._schema_applied_for is None
