"""Tests for SEC-01: schema name validation in BaseDatabaseConfig.

Validates that invalid schema names are rejected at construction time,
protecting all downstream DDL interpolation sites from SQL injection.
"""

import pytest

pytestmark = pytest.mark.unit


def _make_config(schema: str):
    """Create a minimal PostgreSQL config with the given schema."""
    from dblift.db.plugins.postgresql.config import PostgreSqlConfig

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

    def test_double_quoted_identifier_rejected_for_postgresql(self):
        """A quoted schema is Oracle-only; PostgreSQL would emit CREATE SCHEMA \"\"x\"\"."""
        with pytest.raises(ValueError, match="Invalid schema name"):
            _make_config('"myschema"')

    def test_trailing_newline_rejected(self):
        """``$`` would accept a trailing newline; ``fullmatch`` must not."""
        with pytest.raises(ValueError, match="Invalid schema name"):
            _make_config("public\n")

    def test_quoted_identifier_with_injection_rejected(self):
        with pytest.raises(ValueError, match="Invalid schema name"):
            _make_config('"myschema"; DROP TABLE users')

    def test_schema_with_quote_rejected(self):
        with pytest.raises(ValueError, match="Invalid schema name"):
            _make_config("schema'--")

    def test_schema_injection_attempt_rejected(self):
        with pytest.raises(ValueError, match="Invalid schema name"):
            _make_config('"; DROP TABLE users; --')


def _oracle_config(schema: str):
    from dblift.db.plugins.oracle.config import OracleConfig

    return OracleConfig(
        type="oracle",
        url="oracle+oracledb://localhost:1521/?service_name=FREEPDB1",
        username="system",
        password="oracle",
        schema=schema,
    )


class TestQuotedSchemaIsOracleOnly:
    """Other dialects interpolate schema into DDL and must not see quote characters."""

    @pytest.mark.parametrize(
        "config_cls, kwargs",
        [
            (
                "dblift.db.plugins.postgresql.config.PostgreSqlConfig",
                {
                    "type": "postgresql",
                    "url": "postgresql+psycopg://localhost:5432/db",
                    "username": "user",
                    "password": "pass",
                },
            ),
            (
                "dblift.db.plugins.mysql.config.MySqlConfig",
                {
                    "type": "mysql",
                    "url": "mysql+pymysql://localhost:3306/db",
                    "username": "user",
                    "password": "pass",
                },
            ),
            (
                "dblift.db.plugins.sqlserver.config.SqlServerConfig",
                {
                    "type": "sqlserver",
                    "url": "mssql+pyodbc://localhost:1433/db",
                    "username": "user",
                    "password": "pass",
                },
            ),
            (
                "dblift.db.plugins.db2.config.Db2Config",
                {
                    "type": "db2",
                    "url": "ibm_db_sa://localhost:50000/db",
                    "username": "user",
                    "password": "pass",
                },
            ),
            (
                "dblift.db.plugins.sqlite.config.SQLiteConfig",
                {"type": "sqlite", "url": "sqlite:///:memory:"},
            ),
        ],
    )
    def test_non_oracle_dialects_reject_a_quoted_schema(self, config_cls, kwargs):
        import importlib

        module_name, _, cls_name = config_cls.rpartition(".")
        cls = getattr(importlib.import_module(module_name), cls_name)
        with pytest.raises(ValueError, match="Invalid schema name"):
            cls(schema='"x"', **kwargs)

    def test_oracle_accepts_a_quoted_schema(self):
        cfg = _oracle_config('"myschema"')
        assert cfg.schema == '"myschema"'
        mixed = _oracle_config('"MySchema"')
        assert mixed.schema == '"MySchema"'

    def test_oracle_rejects_a_trailing_newline(self):
        with pytest.raises(ValueError, match="Invalid schema name"):
            _oracle_config("myschema\n")
        with pytest.raises(ValueError, match="Invalid schema name"):
            _oracle_config('"myschema"\n')
