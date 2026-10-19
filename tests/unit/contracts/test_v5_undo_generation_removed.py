"""The public API no longer generates text-based undo scripts in v5."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from dblift.api.async_client import AsyncDBLiftClient
from dblift.api.client import DBLiftClient
from dblift.core.logger import results
from dblift.db.base_quirks import BaseQuirks
from dblift.db.plugins.sqlite.quirks import SqliteQuirks

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]


def _migrations(tmp_path: Path) -> Path:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__create_users.sql").write_text(
        "CREATE TABLE users (id INTEGER PRIMARY KEY);\n" "INSERT INTO users (id) VALUES (7);\n",
        encoding="utf-8",
    )
    return migrations


def _rows(db_file: Path) -> list[tuple[int]]:
    with sqlite3.connect(db_file) as connection:
        return connection.execute("SELECT id FROM users ORDER BY id").fetchall()


def _undo_marker_rows(db_file: Path) -> list[tuple[str]]:
    with sqlite3.connect(db_file) as connection:
        return connection.execute("SELECT source FROM undo_marker").fetchall()


@pytest.mark.parametrize("method", ["generate_undo_script", "generate_undo_scripts"])
def test_sync_text_undo_generation_is_removed(tmp_path: Path, method: str) -> None:
    migrations = _migrations(tmp_path)
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    client = DBLiftClient.from_sqlalchemy(
        engine, migrations_dir=migrations, analysis_mode="execution"
    )
    try:
        arguments = (
            (migrations / "V1__create_users.sql",) if method == "generate_undo_script" else ()
        )
        options = {} if arguments else {"migrations_dir": migrations}
        with pytest.raises(AttributeError, match=method):
            getattr(client, method)(*arguments, **options)
        assert not hasattr(type(client), method)
        assert not hasattr(client, method)
    finally:
        client.close()
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["generate_undo_script", "generate_undo_scripts"])
async def test_async_text_undo_generation_is_removed(tmp_path: Path, method: str) -> None:
    migrations = _migrations(tmp_path)
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    client = AsyncDBLiftClient.from_sqlalchemy(
        engine, migrations_dir=migrations, analysis_mode="execution"
    )
    try:
        arguments = (
            (migrations / "V1__create_users.sql",) if method == "generate_undo_script" else ()
        )
        options = {} if arguments else {"migrations_dir": migrations}
        with pytest.raises(AttributeError, match=method):
            await getattr(client, method)(*arguments, **options)
        assert not hasattr(type(client), method)
        assert not hasattr(client, method)
    finally:
        await client.aclose()
        engine.dispose()


def test_text_undo_reverser_package_is_removed() -> None:
    assert importlib.util.find_spec("dblift.core.migration.scripting.undo_script_generator") is None


@pytest.mark.parametrize("quirks_class", [BaseQuirks, SqliteQuirks])
def test_generator_only_quirk_is_removed(quirks_class) -> None:
    assert not hasattr(quirks_class, "undo_reverses_statement_facts")


def test_retired_client_operations_module_is_removed() -> None:
    assert importlib.util.find_spec("dblift.api._client_operations") is None


def test_text_undo_generation_result_is_removed() -> None:
    assert not hasattr(results, "GenerateUndoScriptResult")


def test_sync_hand_authored_undo_and_reapply_remain_executable(tmp_path: Path) -> None:
    migrations = _migrations(tmp_path)
    (migrations / "U1__drop_users.sql").write_text(
        "CREATE TABLE undo_marker (source TEXT NOT NULL);\n"
        "INSERT INTO undo_marker (source) VALUES ('hand-authored U1');\n"
        "DROP TABLE users;\n",
        encoding="utf-8",
    )
    db_file = tmp_path / "app.db"
    engine = create_engine(f"sqlite:///{db_file}")
    client = DBLiftClient.from_sqlalchemy(
        engine, migrations_dir=migrations, analysis_mode="execution"
    )
    try:
        applied = client.migrate()
        assert applied.success, applied.error_message
        assert applied.migrations_applied == ["1"]
        assert client.info().current_schema_version == "1"
        assert _rows(db_file) == [(7,)]

        undone = client.undo()
        assert undone.success, undone.error_message
        assert [migration.version for migration in undone.undone_migrations] == ["1"]
        assert client.info().current_schema_version is None
        assert _undo_marker_rows(db_file) == [("hand-authored U1",)]
        with sqlite3.connect(db_file) as connection:
            assert (
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'users'"
                ).fetchone()
                is None
            )

        reapplied = client.migrate()
        assert reapplied.success, reapplied.error_message
        assert reapplied.migrations_applied == ["1"]
        assert client.info().current_schema_version == "1"
        assert _rows(db_file) == [(7,)]
        assert _undo_marker_rows(db_file) == [("hand-authored U1",)]
    finally:
        client.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_async_hand_authored_undo_and_reapply_remain_executable(tmp_path: Path) -> None:
    migrations = _migrations(tmp_path)
    (migrations / "U1__drop_users.sql").write_text(
        "CREATE TABLE undo_marker (source TEXT NOT NULL);\n"
        "INSERT INTO undo_marker (source) VALUES ('hand-authored U1');\n"
        "DROP TABLE users;\n",
        encoding="utf-8",
    )
    db_file = tmp_path / "app.db"
    engine = create_engine(f"sqlite:///{db_file}")
    client = AsyncDBLiftClient.from_sqlalchemy(
        engine, migrations_dir=migrations, analysis_mode="execution"
    )
    try:
        applied = await client.migrate()
        assert applied.success, applied.error_message
        assert applied.migrations_applied == ["1"]
        assert (await client.info()).current_schema_version == "1"
        assert _rows(db_file) == [(7,)]

        undone = await client.undo()
        assert undone.success, undone.error_message
        assert [migration.version for migration in undone.undone_migrations] == ["1"]
        assert (await client.info()).current_schema_version is None
        assert _undo_marker_rows(db_file) == [("hand-authored U1",)]
        with sqlite3.connect(db_file) as connection:
            assert (
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'users'"
                ).fetchone()
                is None
            )

        reapplied = await client.migrate()
        assert reapplied.success, reapplied.error_message
        assert reapplied.migrations_applied == ["1"]
        assert (await client.info()).current_schema_version == "1"
        assert _rows(db_file) == [(7,)]
        assert _undo_marker_rows(db_file) == [("hand-authored U1",)]
    finally:
        await client.aclose()
        engine.dispose()
