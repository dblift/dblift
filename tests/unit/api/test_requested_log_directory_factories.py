"""Every client construction path resolves explicit logging directories before opening files."""

import pytest
from sqlalchemy import create_engine

from dblift.api.client import DBLiftClient
from dblift.config.dblift_config import DbliftConfig
from dblift.core.logger import NullLog
from tests.unit.cli.test_requested_log_file_cli import _files

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("factory", ["direct", "config", "sqlalchemy"])
def test_explicit_directory_override_reaches_the_default_logger(tmp_path, monkeypatch, factory):
    from dblift.api._cli_support import ProviderRegistry

    monkeypatch.chdir(tmp_path)
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    config = DbliftConfig.from_dict(
        {
            "database": {"type": "sqlite", "path": str(tmp_path / "app.db")},
            "migrations": {"directory": str(migrations)},
            "logging": {"file": "requested.log", "directory": "unused"},
        }
    )
    engine = None
    if factory == "direct":
        provider = ProviderRegistry.create_provider(config, NullLog())
        client = DBLiftClient(provider, migrations, config, log_dir="override")
    elif factory == "config":
        client = DBLiftClient.from_config(config, log_dir="override")
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
        client = DBLiftClient.from_sqlalchemy(engine, config=config, log_dir="override")
    try:
        with client:
            client.logger.info("factory directory override marker")
    finally:
        if engine is not None:
            engine.dispose()
    target = tmp_path / "override" / "requested.log"
    assert _files(tmp_path) == [target]
    assert "factory directory override marker" in target.read_text()
    assert not (tmp_path / "unused").exists()
