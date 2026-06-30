"""Tests for SEC-01: schema name validation in BaseDatabaseConfig.

Validates that invalid schema names are rejected at construction time,
protecting all downstream DDL interpolation sites from SQL injection.
"""

import pytest

pytestmark = pytest.mark.unit


def _make_config(schema: str):
    """Create a minimal PostgreSQL config with the given schema."""
    from db.plugins.postgresql.config import PostgreSqlConfig

    return PostgreSqlConfig(
        type="postgresql",
        url="postgresql+psycopg://localhost:5432/db",
        username="user",
        password="pass",
        schema=schema,
    )


class TestSchemaValidation:
    """SEC-01 — schema names validated at parse time in BaseDatabaseConfig."""

    def test_valid_schema_name_accepted(self):
        cfg = _make_config("public")
        assert cfg.schema == "public"

    def test_schema_with_underscores_accepted(self):
        cfg = _make_config("my_schema")
        assert cfg.schema == "my_schema"

    def test_schema_with_digits_accepted(self):
        cfg = _make_config("schema1")
        assert cfg.schema == "schema1"

    def test_empty_schema_accepted(self):
        cfg = _make_config("")
        assert cfg.schema == ""

    def test_schema_with_semicolon_rejected(self):
        with pytest.raises(ValueError, match="Invalid schema name"):
            _make_config("public; DROP TABLE users --")

    def test_schema_with_dash_rejected(self):
        with pytest.raises(ValueError, match="Invalid schema name"):
            _make_config("my-schema")

    def test_schema_with_dot_rejected(self):
        with pytest.raises(ValueError, match="Invalid schema name"):
            _make_config("schema.name")

    def test_schema_with_space_rejected(self):
        with pytest.raises(ValueError, match="Invalid schema name"):
            _make_config("my schema")

    def test_schema_with_quote_rejected(self):
        with pytest.raises(ValueError, match="Invalid schema name"):
            _make_config("schema'--")

    def test_schema_injection_attempt_rejected(self):
        with pytest.raises(ValueError, match="Invalid schema name"):
            _make_config('"; DROP TABLE users; --')
