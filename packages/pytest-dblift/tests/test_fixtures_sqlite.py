"""SQLite tests for pytest-dblift helpers and fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from api import DBLiftClient


def test_resolve_dblift_config_reads_cli_url(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    from pytest_dblift._client import resolve_dblift_config

    class DummyConfig:
        rootdir = "/tmp"

        def getoption(self, name: str, default: Any = None) -> Any:
            if name == "--dblift-url":
                return "sqlite:////tmp/dblift_custom_test.db"
            if name == "--dblift-migrations-dir":
                return "migrations"
            return default

    cfg = resolve_dblift_config(DummyConfig(), tmp_path_factory=tmp_path_factory)
    assert "dblift_custom_test.db" in cfg["url"]
    assert "migrations" in cfg["migrations_dir"]


def test_worker_id_master_without_xdist(pytestconfig: pytest.Config) -> None:
    from pytest_dblift._client import _worker_id

    if getattr(pytestconfig, "workerinput", None):
        pytest.skip("this assertion is for a non-xdist controller process")
    assert _worker_id(pytestconfig) == "master"


def test_dblift_config_defaults_to_sqlite_file(dblift_config: dict[str, Any]) -> None:
    assert "sqlite" in dblift_config["url"]
    assert ":memory:" not in dblift_config["url"]
    assert (Path(dblift_config["migrations_dir"]) / "V1__init.sql").is_file()


def test_dblift_engine_connects(dblift_engine: Any, dblift_config: dict[str, Any]) -> None:
    from sqlalchemy.engine import Engine

    assert isinstance(dblift_engine, Engine)
    with dblift_engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    rendered = dblift_engine.url.render_as_string(hide_password=False)
    assert rendered.startswith("sqlite")


def test_dblift_client_is_public_client(dblift_client: DBLiftClient) -> None:
    assert isinstance(dblift_client, DBLiftClient)
    info = dblift_client.info()
    assert hasattr(info, "pending_count")


def test_migrated_db_applies_migrations(
    dblift_migrated_db: DBLiftClient, dblift_engine: Any
) -> None:
    assert dblift_migrated_db.info().pending_count == 0
    with dblift_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM pytest_dblift_smoke")).scalar()
        assert count == 0


def test_empty_db_cleans_schema(
    dblift_migrated_db: DBLiftClient, dblift_empty_db: DBLiftClient, dblift_engine: Any
) -> None:
    with dblift_engine.connect() as conn:
        try:
            conn.execute(text("SELECT COUNT(*) FROM pytest_dblift_smoke"))
            exists = True
        except Exception:
            exists = False
    assert not exists


def test_validate_callable_succeeds(
    dblift_migrated_db: DBLiftClient, dblift_validate: Any
) -> None:
    dblift_migrated_db.migrate()
    result = dblift_validate()
    assert result.success is True
    result2 = dblift_validate(target_version=None)
    assert result2.success is True


def test_dblift_validate_is_callable(dblift_validate: Any) -> None:
    assert callable(dblift_validate)
