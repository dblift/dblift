"""Tests for story 14-2: DEDUP database_config from_dict + build_url.

AC#1  — from_dict suppression (5 subclasses inherit base correctly)
AC#2  — _build_standard_url helper direct tests
AC#9  — zero regression (existing tests untouched)
AC#10 — ≥6 direct unit tests on _build_standard_url
"""

import unittest

import pytest

pytestmark = [pytest.mark.unit]

from config.database_config import BaseDatabaseConfig
from db.plugins.db2.config import Db2Config
from db.plugins.mysql.config import MySqlConfig
from db.plugins.oracle.config import OracleConfig
from db.plugins.postgresql.config import PostgreSqlConfig
from db.plugins.sqlserver.config import SqlServerConfig


class TestBuildStandardUrl(unittest.TestCase):
    """AC#10 — Direct unit tests for _build_standard_url()."""

    def _make_config(self, **overrides):
        """Create a PostgreSqlConfig with sensible defaults for testing the helper."""
        defaults = dict(
            type="postgresql",
            host="dbhost",
            port=5432,
            database="mydb",
            username="user",
            password="pass",
            connection_timeout=30,
        )
        defaults.update(overrides)
        return PostgreSqlConfig(**defaults)

    # --- AC#10 test 1: URL fournie → return self.url ---
    def test_returns_url_when_set(self):
        cfg = self._make_config(url="postgresql://already-set")
        result = cfg._build_standard_url("postgresql://", [])
        self.assertEqual(result, "postgresql://already-set")

    # --- AC#10 test 2: sans credentials (include_credentials=False) ---
    def test_without_credentials(self):
        cfg = self._make_config(url="")
        result = cfg._build_standard_url("postgresql+psycopg://", [], include_credentials=False)
        self.assertIn("postgresql+psycopg://dbhost:5432/mydb", result)
        self.assertNotIn("user", result)
        self.assertNotIn("pass", result)

    # --- AC#10 test 3: avec credentials ---
    def test_with_credentials(self):
        cfg = self._make_config(url="")
        result = cfg._build_standard_url("postgresql://", [])
        self.assertTrue(result.startswith("postgresql://user:pass@dbhost:5432/mydb"))

    # --- AC#10 test 4: sans port ---
    def test_without_port(self):
        cfg = self._make_config(url="", port=None)
        result = cfg._build_standard_url("postgresql://", [])
        self.assertIn("postgresql://user:pass@dbhost/mydb", result)

    # --- AC#10 test 5: avec dialect_params ---
    def test_with_dialect_params(self):
        cfg = self._make_config(url="", connection_timeout=0)
        result = cfg._build_standard_url("postgresql://", ["search_path=public", "sslmode=require"])
        self.assertIn("?search_path=public&sslmode=require", result)
        self.assertNotIn("connect_timeout", result)

    # --- AC#10 test 6: avec extra_params ---
    def test_with_extra_params(self):
        cfg = self._make_config(url="", connection_timeout=0, extra_params={"app_name": "dblift"})
        result = cfg._build_standard_url("postgresql://", [])
        self.assertIn("?app_name=dblift", result)

    # --- AC#10 test 7: timeout_key personnalisé ---
    def test_custom_timeout_key(self):
        cfg = self._make_config(url="", connection_timeout=15)
        result = cfg._build_standard_url("postgresql+psycopg://", [], timeout_key="connectTimeout")
        self.assertIn("connectTimeout=15", result)

    # --- AC#10 test 8: sans database ---
    def test_without_database(self):
        cfg = self._make_config(url="", database=None, connection_timeout=0)
        result = cfg._build_standard_url("postgresql://", [])
        self.assertEqual(result, "postgresql://user:pass@dbhost:5432")

    # --- AC#10 test 9: username sans password ---
    def test_username_without_password(self):
        cfg = self._make_config(url="", password="", connection_timeout=0)
        result = cfg._build_standard_url("postgresql://", [])
        self.assertTrue(result.startswith("postgresql://user@dbhost"))

    # --- AC#10 test 10: sans host → localhost ---
    def test_default_localhost(self):
        cfg = self._make_config(url="", host=None, connection_timeout=0)
        result = cfg._build_standard_url("postgresql://", [])
        self.assertIn("postgresql://user:pass@localhost", result)


class TestFromDictInheritance(unittest.TestCase):
    """AC#1 — Verify subclasses inherit from_dict correctly from base."""

    def test_from_dict_not_overridden_in_subclasses(self):
        """AC#1 structural check: from_dict must NOT be in any subclass __dict__."""
        for cls in [SqlServerConfig, OracleConfig, PostgreSqlConfig, MySqlConfig, Db2Config]:
            self.assertNotIn(
                "from_dict",
                cls.__dict__,
                f"{cls.__name__} should not override from_dict (AC#1)",
            )

    def test_sqlserver_from_dict(self):
        data = {
            "type": "sqlserver",
            "url": "mssql+pymssql://h:1433/app",
            "username": "u",
            "password": "p",
        }
        cfg = SqlServerConfig.from_dict(data)
        self.assertIsInstance(cfg, SqlServerConfig)

    def test_oracle_from_dict(self):
        data = {
            "type": "oracle",
            "url": "oracle+oracledb://h:1521?service_name=orcl",
            "username": "u",
            "password": "p",
        }
        cfg = OracleConfig.from_dict(data)
        self.assertIsInstance(cfg, OracleConfig)

    def test_postgresql_from_dict(self):
        data = {
            "type": "postgresql",
            "url": "postgresql+psycopg://h:5432/db",
            "username": "u",
            "password": "p",
        }
        cfg = PostgreSqlConfig.from_dict(data)
        self.assertIsInstance(cfg, PostgreSqlConfig)

    def test_mysql_from_dict(self):
        data = {
            "type": "mysql",
            "url": "mysql+pymysql://h:3306/db",
            "username": "u",
            "password": "p",
        }
        cfg = MySqlConfig.from_dict(data)
        self.assertIsInstance(cfg, MySqlConfig)

    def test_db2_from_dict(self):
        data = {"type": "db2", "url": "ibm_db_sa://h:50000/db", "username": "u", "password": "p"}
        cfg = Db2Config.from_dict(data)
        self.assertIsInstance(cfg, Db2Config)


class TestBuildConnectionStringDelegation(unittest.TestCase):
    """AC#3, AC#4, AC#5 — build_connection_string delegates to _build_standard_url."""

    def test_postgresql_build_connection_string(self):
        cfg = PostgreSqlConfig(
            type="postgresql",
            host="pg",
            port=5432,
            database="db",
            username="u",
            password="p",
            schema="public",
            ssl_mode="require",
            connection_timeout=10,
        )
        url = cfg.build_connection_string()
        self.assertEqual(
            url,
            "postgresql://u:p@pg:5432/db?search_path=public&sslmode=require&connect_timeout=10",
        )

    def test_mysql_build_connection_string(self):
        cfg = MySqlConfig(
            type="mysql",
            host="my",
            port=3306,
            database="db",
            username="u",
            password="p",
            schema="myschema",
            ssl_enabled=True,
            connection_timeout=10,
        )
        url = cfg.build_connection_string()
        self.assertEqual(
            url,
            "mysql://u:p@my:3306/db?schema=myschema&useSSL=true&connect_timeout=10",
        )

    def test_db2_build_connection_string(self):
        cfg = Db2Config(
            type="db2",
            host="db2h",
            port=50000,
            database="db",
            username="u",
            password="p",
            schema="myschema",
            collection="mycol",
            connection_timeout=10,
        )
        url = cfg.build_connection_string()
        self.assertEqual(
            url,
            "ibm_db_sa://u:p@db2h:50000/db?currentSchema=myschema&collection=mycol&connectTimeout=10",
        )


class TestBuildJdbcUrlDelegation(unittest.TestCase):
    """AC#6, AC#7, AC#8 — build_database_url delegates to _build_standard_url."""

    def test_postgresql_build_database_url(self):
        cfg = PostgreSqlConfig(
            type="postgresql",
            host="pg",
            port=5432,
            database="db",
            username="u",
            password="p",
            schema="public",
            ssl_mode="require",
            connection_timeout=10,
        )
        url = cfg.build_database_url()
        self.assertEqual(
            url,
            "postgresql+psycopg://u:p@pg:5432/db?connect_timeout=10&options=-csearch_path%3Dpublic&sslmode=require",
        )
        self.assertIn("u:p", url)

    def test_mysql_build_database_url(self):
        cfg = MySqlConfig(
            type="mysql",
            host="my",
            port=3306,
            database="db",
            username="u",
            password="p",
            schema="myschema",
            ssl_enabled=True,
            connection_timeout=10,
        )
        url = cfg.build_database_url()
        self.assertEqual(
            url,
            "mysql+pymysql://u:p@my:3306/db?connect_timeout=10&ssl=true",
        )
        self.assertNotIn("currentSchema", cfg.get_connection_props())
        self.assertIn("u:p", url)

    def test_mysql_build_database_url_with_options_and_session_variables(self):
        cfg = MySqlConfig(
            type="mysql",
            host="my",
            port=3306,
            database="db",
            username="u",
            password="p",
            connection_timeout=0,
            options={"rewriteBatchedStatements": "true"},
            session_variables={"wait_timeout": "28800"},
        )
        url = cfg.build_database_url()
        self.assertIn("rewriteBatchedStatements=true", url)

    def test_mysql_build_database_url_session_variables_without_options_are_dropped(self):
        """Document pre-existing behavior: session_variables nested inside 'if self.options'.

        When options=None, session_variables are silently omitted from the legacy URL.
        This is intentional (preserved behavior from pre-refactor code).
        """
        cfg = MySqlConfig(
            type="mysql",
            host="my",
            port=3306,
            database="db",
            username="u",
            password="p",
            connection_timeout=0,
            options=None,
            session_variables={"wait_timeout": "28800"},
        )
        url = cfg.build_database_url()
        self.assertNotIn("sessionVariables", url)

    def test_db2_build_database_url(self):
        cfg = Db2Config(
            type="db2",
            host="db2h",
            port=50000,
            database="db",
            username="u",
            password="p",
            schema="myschema",
            collection="mycol",
            connection_timeout=10,
        )
        url = cfg.build_database_url()
        self.assertEqual(
            url,
            "ibm_db_sa://u:p@db2h:50000/db?collection=mycol&connectTimeout=10&currentSchema=myschema",
        )


if __name__ == "__main__":
    unittest.main()
