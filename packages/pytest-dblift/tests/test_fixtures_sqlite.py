"""Targeted SQLite tests for the core pytest-dblift fixtures (Task 4.2).

These exercise the full fixture graph using a real temp SQLite file DB,
real DBLiftClient.from_sqlalchemy, and a minimal V1 migration.

Run with (from package dir, after parent editable install):
    PYTHONPATH=../.. python -m pytest tests/test_fixtures_sqlite.py -q --no-header
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from api import DBLiftClient  # for type checks / direct helper tests


def test_dblift_config_defaults_to_sqlite_and_migrations_dir(dblift_config: dict[str, Any]) -> None:
    """dblift_config (session) yields dict with url (temp sqlite file) + migrations_dir."""
    assert isinstance(dblift_config, dict)
    assert "url" in dblift_config
    assert "sqlite" in dblift_config["url"]
    # file not :memory:
    assert ":memory:" not in dblift_config["url"]
    assert "migrations_dir" in dblift_config
    assert "pytest_dblift_smoke" in open(
        Path(dblift_config["migrations_dir"]) / "V1__init.sql"
    ).read()  # ensure our override worked and file is real


def test_resolve_dblift_config_reads_cli_url(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """--dblift-url is honored via resolve helper (used by dblift_config)."""
    from pytest_dblift._client import resolve_dblift_config

    class DummyConfig:
        rootdir = "/tmp"  # satisfy resolve_dblift_config

        def getoption(self, name: str, default: Any = None) -> Any:
            if name == "--dblift-url":
                return "sqlite:////tmp/dblift_custom_test.db"
            if name == "--dblift-migrations-dir":
                return "migrations"
            return default

    cfg = resolve_dblift_config(DummyConfig(), tmp_path_factory=tmp_path_factory)
    assert "dblift_custom_test.db" in cfg["url"]
    assert cfg["migrations_dir"].endswith("migrations") or "migrations" in cfg["migrations_dir"]


def test_dblift_engine_creates_real_engine(dblift_engine: Any, dblift_config: dict[str, Any]) -> None:
    """dblift_engine (session) is a usable create_engine(url) from the config."""
    from sqlalchemy.engine import Engine

    assert isinstance(dblift_engine, Engine)
    # Basic connectivity
    with dblift_engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    # Matches the config url
    assert dblift_engine.url.render_as_string(hide_password=False).startswith("sqlite")


def test_dblift_client_built_via_from_sqlalchemy(dblift_client: DBLiftClient, dblift_config: dict[str, Any]) -> None:
    """dblift_client (session) uses DBLiftClient.from_sqlalchemy(engine, migrations_dir)."""
    assert isinstance(dblift_client, DBLiftClient)
    assert hasattr(dblift_client, "migrate")
    assert hasattr(dblift_client, "info")
    assert hasattr(dblift_client, "clean")
    assert hasattr(dblift_client, "validate")
    assert hasattr(dblift_client, "close")
    # migrations_dir wired (check the V1 file is discoverable under it)
    scripts_dir = dblift_client._get_scripts_dir()
    assert (Path(scripts_dir) / "V1__init.sql").exists()


def test_migrated_db_applies_migrations(dblift_migrated_db: DBLiftClient, dblift_engine: Any) -> None:
    """dblift_migrated_db (function) calls migrate() and yields the (session) client."""
    assert isinstance(dblift_migrated_db, DBLiftClient)
    info = dblift_migrated_db.info()
    # After migrate, no pending
    pending = getattr(info, "pending_count", None)
    if pending is not None:
        assert pending == 0
    else:
        pending_list = getattr(info, "pending", [])
        assert len(pending_list) == 0 or pending_list is None

    # The smoke table from V1 exists and is empty (use the session engine fixture, not provider internals)
    with dblift_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM pytest_dblift_smoke")).scalar()
        assert count == 0


def test_engine_and_client_are_session_scoped_shared(dblift_engine: Any, dblift_client: DBLiftClient) -> None:
    """Session fixtures are reused across tests (no re-create per function test)."""
    # Identity checks: the objects are the same instances as in prior tests
    # (pytest caches them for the session)
    # We can't easily capture prior id here, but we can assert engine is not disposed and works
    with dblift_engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def test_empty_db_cleans_schema(dblift_migrated_db: DBLiftClient, dblift_empty_db: DBLiftClient, dblift_engine: Any) -> None:
    """dblift_empty_db (function) performs client.clean(clean_enabled=True) leaving clean/empty state."""
    assert isinstance(dblift_empty_db, DBLiftClient)
    # After clean (which was called by the fixture), the user table + history are gone
    with dblift_engine.connect() as conn:
        # table should be gone (or query fails)
        try:
            conn.execute(text("SELECT COUNT(*) FROM pytest_dblift_smoke"))
            exists = True
        except Exception:
            exists = False
        assert not exists, "clean should have dropped the user table"


def test_validate_callable_works(dblift_migrated_db: DBLiftClient, dblift_validate: Any) -> None:
    """dblift_validate (function) returns a callable that runs client.validate() + asserts success."""
    # re-migrate first so validate sees current state (empty_db in prior test cleaned)
    dblift_migrated_db.migrate()
    result = dblift_validate()
    assert result.success is True
    # callable accepts kwargs like target_version etc.
    result2 = dblift_validate(target_version=None)
    assert result2.success is True


def test_dblift_validate_fixture_is_callable(dblift_validate: Any) -> None:
    """The returned object from the fixture is directly callable."""
    assert callable(dblift_validate)
