from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.logger import NullLog
from core.logger.results import MigrateResult
from core.migration.executor.execution_engine import ExecutionEngine
from core.migration.executor.transaction_policy import TransactionPolicy
from core.migration.migration import Migration, MigrationType
from core.migration.sql.execution_statement import (
    ExecutionStatement,
    classify_execution_statement,
)
from core.migration.sql.sql_analyzer import SqlAnalyzer
from db.provider_interfaces import TransactionalProvider


class RecordingTransactionalProvider(TransactionalProvider):
    def __init__(self):
        self.events = []

    def begin_transaction(self) -> None:
        self.events.append("begin")

    def commit_transaction(self) -> None:
        self.events.append("commit")

    def rollback_transaction(self) -> None:
        self.events.append("rollback")

    def supports_transactions(self) -> bool:
        return True

    def execute_query(self, sql, params=None):
        self.events.append("query")
        return []

    def execute_statement(self, sql, schema=None, params=None):
        self.events.append(f"execute:{sql.strip()}")
        return 0

    def execute_autocommit_statement(self, sql, schema=None, params=None):
        self.events.append(f"autocommit:{sql.strip()}")
        return 0


@pytest.mark.unit
def test_postgresql_create_index_concurrently_requires_autocommit():
    statement = classify_execution_statement(
        "CREATE INDEX CONCURRENTLY idx_users_email ON users(email)",
        dialect="postgresql",
        statement_type="DDL",
    )

    assert statement.can_execute_in_transaction is False
    assert "CONCURRENTLY" in (statement.transaction_reason or "")


@pytest.mark.unit
@pytest.mark.parametrize(
    "sql",
    [
        "REINDEX TABLE CONCURRENTLY orders",
        "REINDEX INDEX CONCURRENTLY idx_orders_id",
        "DROP INDEX CONCURRENTLY idx_orders_id",
    ],
)
def test_postgresql_concurrently_maintenance_commands_require_autocommit(sql):
    statement = classify_execution_statement(sql, dialect="postgresql", statement_type="DDL")

    assert statement.can_execute_in_transaction is False
    assert "CONCURRENTLY" in (statement.transaction_reason or "")


@pytest.mark.unit
@pytest.mark.parametrize(
    "sql",
    [
        "REINDEX TABLE orders",
        "REINDEX INDEX idx_orders_id",
        "DROP INDEX idx_orders_id",
    ],
)
def test_postgresql_non_concurrently_maintenance_commands_run_in_transaction(sql):
    statement = classify_execution_statement(sql, dialect="postgresql", statement_type="DDL")

    assert statement.can_execute_in_transaction is True


@pytest.mark.unit
def test_sqlserver_create_fulltext_catalog_requires_autocommit():
    statement = classify_execution_statement(
        "CREATE FULLTEXT CATALOG dblift_ft_catalog AS DEFAULT",
        dialect="sqlserver",
        statement_type="DDL",
    )

    assert statement.can_execute_in_transaction is False
    assert "FULLTEXT CATALOG" in (statement.transaction_reason or "")


@pytest.mark.unit
def test_sqlserver_create_fulltext_index_requires_autocommit():
    statement = classify_execution_statement(
        "CREATE FULLTEXT INDEX ON dbo.articles(body) KEY INDEX pk_articles",
        dialect="sqlserver",
        statement_type="DDL",
    )

    assert statement.can_execute_in_transaction is False
    assert "FULLTEXT" in (statement.transaction_reason or "")


@pytest.mark.unit
def test_sqlserver_drop_fulltext_index_requires_autocommit():
    statement = classify_execution_statement(
        "DROP FULLTEXT INDEX ON dbo.articles",
        dialect="sqlserver",
        statement_type="DDL",
    )

    assert statement.can_execute_in_transaction is False
    assert "FULLTEXT" in (statement.transaction_reason or "")


@pytest.mark.unit
def test_sqlserver_drop_fulltext_catalog_requires_autocommit():
    statement = classify_execution_statement(
        "DROP FULLTEXT CATALOG dblift_ft_catalog",
        dialect="sqlserver",
        statement_type="DDL",
    )

    assert statement.can_execute_in_transaction is False
    assert "FULLTEXT CATALOG" in (statement.transaction_reason or "")


@pytest.mark.unit
def test_transaction_policy_rejects_mixed_autocommit_and_transactional_statements():
    policy = TransactionPolicy()

    decision = policy.decide(
        [
            ExecutionStatement("CREATE TABLE users(id int)", "DDL"),
            classify_execution_statement(
                "CREATE INDEX CONCURRENTLY idx_users_id ON users(id)",
                dialect="postgresql",
                statement_type="DDL",
            ),
        ],
        RecordingTransactionalProvider(),
    )

    assert decision.unsupported_mixed_mode is True
    assert decision.autocommit_required is True


@pytest.mark.unit
def test_execution_engine_runs_autocommit_only_statement_without_migration_transaction():
    provider = RecordingTransactionalProvider()
    history_manager = MagicMock()
    engine = ExecutionEngine(
        provider=provider,
        sql_analyzer=SqlAnalyzer(dialect="postgresql"),
        log=NullLog(),
        history_manager=history_manager,
    )
    migration = Migration(
        script_name="V1__index.sql",
        content="CREATE INDEX CONCURRENTLY idx_users_id ON users(id);",
        version="1",
        description="index",
        type=MigrationType.SQL,
    )
    result = MigrateResult()

    engine.execute_migration(migration, result)

    assert result.success is True
    # The flagged statement goes through the provider's autocommit call — the
    # provider owns how it reaches the server outside a transaction block.
    assert "autocommit:CREATE INDEX CONCURRENTLY idx_users_id ON users(id);" in provider.events
    assert provider.events[-2:] == ["begin", "commit"]
    assert provider.events.count("begin") == 1
    history_manager.record_migration.assert_called_once()


@pytest.mark.unit
def test_execution_engine_runs_sqlserver_fulltext_catalog_without_migration_transaction():
    provider = RecordingTransactionalProvider()
    history_manager = MagicMock()
    engine = ExecutionEngine(
        provider=provider,
        sql_analyzer=SqlAnalyzer(dialect="sqlserver"),
        log=NullLog(),
        history_manager=history_manager,
    )
    migration = Migration(
        script_name="V1__fulltext.sql",
        content="CREATE FULLTEXT CATALOG dblift_ft_catalog AS DEFAULT;",
        version="1",
        description="fulltext",
        type=MigrationType.SQL,
    )
    result = MigrateResult()

    engine.execute_migration(migration, result)

    assert result.success is True
    assert "autocommit:CREATE FULLTEXT CATALOG dblift_ft_catalog AS DEFAULT;" in provider.events
    assert provider.events[-2:] == ["begin", "commit"]
    assert provider.events.count("begin") == 1
    history_manager.record_migration.assert_called_once()


@pytest.mark.unit
def test_execution_engine_rejects_mixed_transaction_policy_before_execution():
    provider = RecordingTransactionalProvider()
    engine = ExecutionEngine(
        provider=provider,
        sql_analyzer=SqlAnalyzer(dialect="postgresql"),
        log=NullLog(),
    )
    migration = Migration(
        script_name="V1__mixed.sql",
        content="""
        CREATE TABLE users(id int);
        CREATE INDEX CONCURRENTLY idx_users_id ON users(id);
        """,
        version="1",
        description="mixed",
        type=MigrationType.SQL,
    )
    result = MigrateResult()

    engine.execute_migration(migration, result)

    assert result.success is False
    assert "mixes transactional and autocommit-only statements" in (result.error_message or "")
    assert not any(event.startswith("execute:") for event in provider.events)


@pytest.mark.unit
def test_get_executable_sql_statements_rejects_mixed_transaction_policy():
    provider = RecordingTransactionalProvider()
    engine = ExecutionEngine(
        provider=provider,
        sql_analyzer=SqlAnalyzer(dialect="postgresql"),
        log=NullLog(),
    )
    migration = Migration(
        script_name="V1__mixed.sql",
        content="""
        CREATE TABLE users(id int);
        CREATE INDEX CONCURRENTLY idx_users_id ON users(id);
        """,
        version="1",
        description="mixed",
        type=MigrationType.SQL,
    )
    result = MigrateResult()

    statements = engine.get_executable_sql_statements(migration, result)

    assert statements == []
    assert result.success is False
    assert "mixes transactional and autocommit-only statements" in (result.error_message or "")
