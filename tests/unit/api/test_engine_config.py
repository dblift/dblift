"""Unit tests for config_from_engine (api/_engine_config)."""

from sqlalchemy import create_engine

from api._engine_config import config_from_engine


def test_config_from_engine_postgresql():
    engine = create_engine("postgresql+psycopg://u:p@localhost/app")
    config = config_from_engine(engine, schema="app")
    assert config.database.type == "postgresql"
    assert config.database.schema == "app"
    assert "postgresql" in config.database.url


def test_config_from_engine_sqlite():
    """SQLite is a first-class supported dialect."""
    engine = create_engine("sqlite:///:memory:")
    config = config_from_engine(engine)
    assert config.database.type in ("sqlite", "sqlite3")
    assert ":memory:" in str(config.database.url) or config.database.url == "sqlite:///:memory:"
