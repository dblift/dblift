"""SQLite transaction probes retain their native query path."""

import sqlite3

import pytest
from sqlalchemy import create_engine, text

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.exceptions import TransactionAbortedError
from dblift.db.plugins.sqlite.provider import SQLiteProvider


@pytest.mark.unit
@pytest.mark.sqlite
def test_probe_query_physical_trace() -> None:
    provider = SQLiteProvider(
        DbliftConfig.from_dict({"database": {"type": "sqlite", "path": ":memory:"}})
    )
    connection = provider.create_connection()
    sends: list[str] = []
    connection.set_trace_callback(sends.append)
    try:
        provider.begin_transaction()
        assert provider.execute_query(provider.quirks.connection_probe_sql) == [{"1": 1}]
        assert sends == ["SELECT 1", "BEGIN IMMEDIATE", "SELECT 1", "SELECT 1", "SELECT 1"]
        provider.rollback_transaction()
    finally:
        provider.close()


@pytest.mark.unit
@pytest.mark.sqlite
def test_health_hook_preserves_physical_probe_count() -> None:
    provider = SQLiteProvider(
        DbliftConfig.from_dict({"database": {"type": "sqlite", "path": ":memory:"}})
    )
    connection = provider.create_connection()
    sends: list[str] = []
    connection.set_trace_callback(sends.append)
    try:
        provider.begin_transaction()
        provider.check_transaction_state()
        assert sends == ["SELECT 1", "BEGIN IMMEDIATE", "SELECT 1", "SELECT 1", "SELECT 1"]
        assert connection.in_transaction
        provider.rollback_transaction()
    finally:
        provider.close()


@pytest.mark.unit
@pytest.mark.sqlite
def test_health_hook_maps_only_aborted_query_errors(monkeypatch) -> None:
    provider = SQLiteProvider(
        DbliftConfig.from_dict({"database": {"type": "sqlite", "path": ":memory:"}})
    )
    aborted = sqlite3.OperationalError("current transaction is aborted")

    def fail_aborted(sql):
        assert sql == provider.quirks.connection_probe_sql
        raise aborted

    monkeypatch.setattr(provider, "execute_query", fail_aborted)
    with pytest.raises(TransactionAbortedError) as exc:
        provider.check_transaction_state()
    assert exc.value.__cause__ is aborted
    assert str(aborted) in str(exc.value)

    other = sqlite3.OperationalError("connection lost")

    def fail_other(sql):
        raise other

    monkeypatch.setattr(provider, "execute_query", fail_other)
    with pytest.raises(sqlite3.OperationalError) as exc:
        provider.check_transaction_state()
    assert exc.value is other


@pytest.mark.unit
@pytest.mark.sqlite
def test_caller_transaction_state_tolerates_an_invalidated_connection() -> None:
    config = DbliftConfig.from_dict({"database": {"type": "sqlite", "path": ":memory:"}})
    provider = SQLiteProvider(config)
    engine = create_engine("sqlite:///:memory:")
    connection = engine.connect()
    provider.attach_external_sqlalchemy(engine, connection)
    connection.invalidate()
    try:
        assert provider.caller_transaction_active() is False
    finally:
        engine.dispose()


@pytest.mark.unit
@pytest.mark.sqlite
def test_context_exit_rolls_back_an_explicit_provider_transaction(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.connect() as connection:
            connection.execute(text("CREATE TABLE mine (id INTEGER)"))
            connection.commit()
            client = DBLiftClient.from_sqlalchemy(connection=connection, migrations_dir=tmp_path)
            client.provider.begin_transaction()
            client.provider.execute_statement("INSERT INTO mine VALUES (1)")
            with pytest.raises(ValueError, match="caller exception"):
                with client:
                    raise ValueError("caller exception")
            assert connection.execute(text("SELECT COUNT(*) FROM mine")).scalar() == 0
    finally:
        engine.dispose()
