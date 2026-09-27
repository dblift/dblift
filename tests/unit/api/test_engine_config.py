"""Unit tests for config_from_engine (api/_engine_config)."""

from sqlalchemy import create_engine, make_url

from dblift.api._engine_config import config_from_engine


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
    # SQLAlchemy 2.1 percent-encodes the database part when rendering the URL
    # (sqlite:///%3Amemory%3A); compare the parsed database, not the string.
    assert make_url(config.database.url).database == ":memory:"
