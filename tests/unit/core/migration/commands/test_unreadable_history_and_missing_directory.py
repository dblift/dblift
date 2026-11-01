"""``info`` and ``migrate`` stop on state they cannot read, as ``validate`` does."""

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient

pytestmark = pytest.mark.unit

DENIED = 'permission denied for table "dblift_schema_history"'


@pytest.fixture
def scripts(tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "V1__init.sql").write_text("CREATE TABLE items (id INTEGER);")
    return directory


@pytest.fixture
def make_client(tmp_path):
    clients = []

    def make(migrations_dir):
        engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
        client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations_dir))
        clients.append((client, engine))
        return client

    yield make
    for client, engine in clients:
        client.close()
        engine.dispose()


@pytest.mark.parametrize("operation", ["info", "migrate_dry_run"])
def test_unreadable_history_is_an_error_not_an_empty_history(
    make_client, scripts, monkeypatch, operation
):
    client = make_client(scripts)
    assert client.migrate().success
    monkeypatch.setattr(
        client.provider,
        "get_applied_migrations",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError(DENIED)),
    )

    result = client.info() if operation == "info" else client.migrate(dry_run=True)

    assert not result.success
    assert "permission denied" in result.error_message


@pytest.mark.parametrize("operation", ["info", "migrate", "migrate_dry_run", "validate"])
def test_missing_migrations_directory_fails_like_validate(make_client, tmp_path, operation):
    missing = tmp_path / "does-not-exist"
    client = make_client(missing)

    if operation == "info":
        result = client.info()
    elif operation == "validate":
        result = client.validate()
    else:
        result = client.migrate(dry_run=operation == "migrate_dry_run")

    assert not result.success
    assert f"Migration scripts directory not found: {missing}" in result.error_message
