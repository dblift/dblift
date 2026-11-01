"""``_prepare_transaction`` on a caller-owned connection re-applies the schema.

Its rollback undoes the ``SET search_path`` (``provider._tx`` stays ``None``).
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


def test_prepare_transaction_on_external_connection_reapplies_schema():
    provider = _Provider()
    config = MagicMock()
    config.database.schema = "app"
    engine = ExecutionEngine(
        provider=provider, sql_analyzer=MagicMock(), log=MagicMock(), config=config
    )
    migration = MagicMock(spec=Migration)
    migration.format = MigrationFormat.SQL
    migration.script_name = "V1__init.sql"
    issued: list = []

    with patch.object(SqlAlchemyProvider, "begin_transaction", lambda self: None):
        with patch.object(
            SqlAlchemyProvider, "execute_statement", lambda self, sql, *a, **k: issued.append(sql)
        ):
            started = engine._prepare_transaction(migration)

    assert started
    assert len([sql for sql in issued if sql.startswith("SET search_path")]) == 1
    assert provider._schema_applied_for == "app"


def test_prepare_transaction_rolls_back_when_reapplying_the_schema_fails():
    provider = _Provider()
    config = MagicMock()
    config.database.schema = "app"
    engine = ExecutionEngine(
        provider=provider, sql_analyzer=MagicMock(), log=MagicMock(), config=config
    )
    migration = MagicMock(spec=Migration)
    migration.format = MigrationFormat.SQL
    migration.script_name = "V1__init.sql"
    calls: list = []

    def fail(self, schema):
        raise RuntimeError("set failed")

    with patch.object(SqlAlchemyProvider, "begin_transaction", lambda self: calls.append("begin")):
        with patch.object(PostgreSqlProvider, "set_current_schema", fail):
            with patch.object(
                SqlAlchemyProvider, "rollback_transaction", lambda self: calls.append("rollback")
            ):
                started = engine._prepare_transaction(migration)

    assert not started
    assert calls == ["rollback", "begin", "rollback"]  # the first one is the defensive rollback
