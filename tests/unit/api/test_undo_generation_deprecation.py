"""Text-based undo script generation is deprecated on both clients.

Each entry point warns with ``DeprecationWarning`` attributed to the caller's
line, and still generates the same undo script it did before.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from dblift.api.async_client import AsyncDBLiftClient
from dblift.api.client import DBLiftClient

pytestmark = [pytest.mark.unit]

MESSAGE = "text-based undo script generation is deprecated"


def _migrations(tmp_path: Path) -> Path:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text("CREATE TABLE app_users (id INTEGER PRIMARY KEY);")
    return migrations


def _engine(tmp_path: Path):
    return create_engine(f"sqlite:///{tmp_path / 'app.db'}")


def _assert_warned_at_caller(record) -> None:
    filenames = [w.filename for w in record if issubclass(w.category, DeprecationWarning)]
    assert __file__ in filenames


def _assert_undo_drops_table(path) -> None:
    assert "DROP TABLE" in Path(path).read_text().upper()


def test_generate_undo_script_warns_and_still_generates(tmp_path):
    migrations = _migrations(tmp_path)
    client = DBLiftClient.from_sqlalchemy(_engine(tmp_path), migrations_dir=migrations)

    with pytest.warns(DeprecationWarning, match=MESSAGE) as record:
        result = client.generate_undo_script(migrations / "V1__init.sql")

    _assert_warned_at_caller(record)
    assert result.success, result.error_message
    _assert_undo_drops_table(result.undo_script_path)
    client.close()


def test_generate_undo_scripts_warns_and_still_generates(tmp_path):
    migrations = _migrations(tmp_path)
    client = DBLiftClient.from_sqlalchemy(_engine(tmp_path), migrations_dir=migrations)

    with pytest.warns(DeprecationWarning, match=MESSAGE) as record:
        results = client.generate_undo_scripts(migrations_dir=migrations)

    _assert_warned_at_caller(record)
    assert [r.success for r in results] == [True]
    _assert_undo_drops_table(results[0].undo_script_path)
    client.close()


@pytest.mark.asyncio
async def test_async_generate_undo_script_warns_and_still_generates(tmp_path):
    migrations = _migrations(tmp_path)
    client = AsyncDBLiftClient.from_sqlalchemy(_engine(tmp_path), migrations_dir=migrations)

    with pytest.warns(DeprecationWarning, match=MESSAGE) as record:
        result = await client.generate_undo_script(migrations / "V1__init.sql")

    _assert_warned_at_caller(record)
    assert result.success, result.error_message
    _assert_undo_drops_table(result.undo_script_path)
    await client.aclose()


@pytest.mark.asyncio
async def test_async_generate_undo_scripts_warns_and_still_generates(tmp_path):
    migrations = _migrations(tmp_path)
    client = AsyncDBLiftClient.from_sqlalchemy(_engine(tmp_path), migrations_dir=migrations)

    with pytest.warns(DeprecationWarning, match=MESSAGE) as record:
        results = await client.generate_undo_scripts(migrations_dir=migrations)

    _assert_warned_at_caller(record)
    assert [r.success for r in results] == [True]
    _assert_undo_drops_table(results[0].undo_script_path)
    await client.aclose()
