"""Unit tests for BaseSnapshotManager (Story X-1 — JdbcProvider decomposition).

Tests are mock-based: BaseSnapshotManager only depends on a duck-typed
``provider`` interface, so we exercise it without any JVM/JDBC setup.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from db.plugins.base_snapshot_manager import BaseSnapshotManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeConnection:
    def __init__(self, autocommit: bool = False) -> None:
        self._autocommit = autocommit
        self.commit_called = 0
        self.rollback_called = 0

    def getAutoCommit(self) -> bool:
        return self._autocommit

    def commit(self) -> None:
        self.commit_called += 1

    def rollback(self) -> None:
        self.rollback_called += 1


def _make_provider(
    dialect: str = "postgresql",
    table_exists: bool = False,
    execute_side_effect=None,
    autocommit: bool = False,
    connection: object | None = None,
):
    """Build a duck-typed provider matching BaseSnapshotManager's contract."""
    provider = MagicMock()
    provider.log = MagicMock()
    provider.config = SimpleNamespace(database=SimpleNamespace(type=dialect))
    provider.is_connected.return_value = True
    provider.create_connection = MagicMock()
    provider.create_schema_if_not_exists = MagicMock()
    provider.get_normalized_object_name = lambda name: name
    provider.table_exists.return_value = table_exists
    provider.get_schema_qualified_name = lambda schema, name: f"{schema}.{name}"
    provider.commit_transaction = MagicMock()

    executed: list[str] = []

    def _exec(sql, schema=None, params=None):
        if execute_side_effect is not None:
            execute_side_effect(sql)
        executed.append(sql)
        return 1

    provider.execute_statement = MagicMock(side_effect=_exec)
    provider.executed_sqls = executed

    provider.connection = connection if connection is not None else _FakeConnection(autocommit)
    return provider


# ---------------------------------------------------------------------------
# AC#5 — Dialect coverage (6 dialects × CREATE + short-circuit)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDialectSql:
    def test_postgresql_uses_text(self):
        provider = _make_provider("postgresql")
        BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("public")
        assert any("TEXT" in s and "snapshot_id" in s for s in provider.executed_sqls)

    def test_oracle_opts_out_of_snapshot_table_ddl(self):
        provider = _make_provider("oracle")
        with pytest.raises(NotImplementedError, match="Oracle snapshot table DDL"):
            BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("myschema")
        assert provider.executed_sqls == []

    def test_mysql_opts_out_of_snapshot_table_ddl(self):
        provider = _make_provider("mysql")
        with pytest.raises(NotImplementedError, match="MySQL does not support"):
            BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("db")
        assert provider.executed_sqls == []

    def test_mariadb_opts_out_of_snapshot_table_ddl(self):
        provider = _make_provider("mariadb")
        with pytest.raises(NotImplementedError, match="MariaDB snapshots are not provider-owned"):
            BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("db")
        assert provider.executed_sqls == []

    def test_sqlserver_opts_out_of_snapshot_table_ddl(self):
        provider = _make_provider("sqlserver")
        with pytest.raises(
            NotImplementedError, match="SQL Server snapshots are not provider-owned"
        ):
            BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("dbo")
        assert provider.executed_sqls == []

    def test_db2_opts_out_of_snapshot_table_ddl(self):
        provider = _make_provider("db2")
        with pytest.raises(NotImplementedError, match="DB2 does not support"):
            BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("myschema")
        assert provider.executed_sqls == []


# ---------------------------------------------------------------------------
# Short-circuit: table already exists
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestShortCircuit:
    @pytest.mark.parametrize(
        "dialect", ["postgresql", "oracle", "mysql", "mariadb", "sqlserver", "db2"]
    )
    def test_skips_when_table_exists(self, dialect):
        provider = _make_provider(dialect, table_exists=True)
        BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("any")
        assert provider.executed_sqls == []
        assert provider.execute_statement.call_count == 0


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConnectionLifecycle:
    def test_create_connection_called_when_not_connected(self):
        provider = _make_provider()
        provider.is_connected.side_effect = [False, True]
        BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("public")
        assert provider.create_connection.call_count >= 1

    def test_commit_on_non_autocommit(self):
        provider = _make_provider(autocommit=False)
        BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("public")
        assert provider.connection.commit_called == 1

    def test_no_commit_on_autocommit(self):
        provider = _make_provider(autocommit=True)
        BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("public")
        assert provider.connection.commit_called == 0


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestErrorPaths:
    def test_non_oracle_error_reraises(self):
        def boom(sql):
            if "CREATE TABLE" in sql:
                raise RuntimeError("disk full")

        provider = _make_provider("postgresql", execute_side_effect=boom)
        with pytest.raises(RuntimeError, match="disk full"):
            BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("public")

    def test_rollback_on_error_non_autocommit(self):
        def boom(sql):
            if "CREATE TABLE" in sql:
                raise RuntimeError("create failed")

        provider = _make_provider("postgresql", execute_side_effect=boom, autocommit=False)
        with pytest.raises(RuntimeError):
            BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("public")
        assert provider.connection.rollback_called == 1

    def test_commit_exception_falls_back_to_commit_transaction(self):
        class BrokenConn(_FakeConnection):
            def getAutoCommit(self):
                raise RuntimeError("conn broken")

        provider = _make_provider("postgresql", connection=BrokenConn())
        # Should not raise; fallback path exercised
        BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("public")
        provider.commit_transaction.assert_called_once()


# ---------------------------------------------------------------------------
# ADR-26: provider-compat snapshot DDL hooks default to "no compat"
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProviderCompatSnapshotDefaults:
    def test_base_quirks_compat_ddl_defaults_to_none(self):
        from db.base_quirks import BaseQuirks

        assert BaseQuirks().build_provider_compat_snapshot_ddl("t.snap", 100, 128) is None

    def test_base_quirks_skip_existence_check_defaults_false(self):
        from db.base_quirks import BaseQuirks

        assert BaseQuirks().provider_compat_snapshot_skips_existence_check is False


# ---------------------------------------------------------------------------
# ADR-26: live provider-compat path (real native provider class)
# ---------------------------------------------------------------------------


def _mysql_compat_provider(table_exists: bool):
    """A provider whose class declares canonical_dialect_key='mysql', so the
    manager's uses_compat gate is True (unlike a bare MagicMock)."""
    base = _make_provider("mysql", table_exists=table_exists)

    class _MySqlLike:
        canonical_dialect_key = "mysql"

    base.__class__ = _MySqlLike  # gate reads type(self._provider)
    return base


@pytest.mark.unit
class TestLiveProviderCompatPath:
    def test_mysql_compat_emits_innodb_ddl_and_skips_existence_check(self):
        # table_exists=True must NOT short-circuit for mysql compat.
        provider = _mysql_compat_provider(table_exists=True)
        BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("db")
        assert any(
            "ENGINE=InnoDB" in s and "CREATE TABLE IF NOT EXISTS" in s
            for s in provider.executed_sqls
        )

    def test_mysql_compat_ddl_uses_constants(self):
        provider = _mysql_compat_provider(table_exists=False)
        BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("db")
        assert any("model_data LONGTEXT NOT NULL" in s for s in provider.executed_sqls)


def _compat_provider(dialect: str, table_exists: bool):
    """A provider whose class declares canonical_dialect_key=<dialect>, so the
    manager's uses_compat gate is True (unlike a bare MagicMock)."""
    base = _make_provider(dialect, table_exists=table_exists)

    class _NativeLike:
        canonical_dialect_key = dialect

    base.__class__ = _NativeLike  # gate reads type(self._provider)
    return base


@pytest.mark.unit
class TestLiveOracleCompatPath:
    def test_oracle_compat_keeps_existence_check(self):
        # Oracle does NOT skip the existence check; an existing table short-circuits.
        provider = _compat_provider("oracle", table_exists=True)
        BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("s")
        assert provider.executed_sqls == []

    def test_oracle_compat_emits_clob_plain_create(self):
        provider = _compat_provider("oracle", table_exists=False)
        BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("s")
        assert any(
            "MODEL_DATA CLOB NOT NULL" in s and "CREATE TABLE IF NOT EXISTS" not in s
            for s in provider.executed_sqls
        )


@pytest.mark.unit
class TestLiveMariadbCompatPath:
    def test_mariadb_compat_reraises_not_implemented(self):
        # uses_compat gate is True, but MariaDB's compat DDL is None -> re-raise.
        provider = _compat_provider("mariadb", table_exists=False)
        with pytest.raises(NotImplementedError):
            BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("db")
        assert provider.executed_sqls == []

    def test_mariadb_compat_keeps_existence_check(self):
        # Skip-flag reset to False, so an existing table short-circuits (no raise).
        provider = _compat_provider("mariadb", table_exists=True)
        BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("db")
        assert provider.executed_sqls == []
