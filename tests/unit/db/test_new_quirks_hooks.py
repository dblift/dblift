"""Tests for new BaseQuirks hooks added in dialect-boundary-cleanup.

Story 1: introspector_class, non_transactional_sql_patterns,
         existence_check_sql, fk_reference_query, index_reference_query.
Story 2: IntrospectorFactory quirks-driven registration.
"""

import pytest

from db.base_quirks import BaseQuirks

# ---------------------------------------------------------------------------
# BaseQuirks defaults
# ---------------------------------------------------------------------------


def test_introspector_class_default_returns_none():
    assert BaseQuirks("pg").introspector_class() is None


def test_non_transactional_patterns_default_empty():
    assert BaseQuirks("pg").non_transactional_sql_patterns == ()


def test_existence_check_sql_default_uses_limit():
    sql = BaseQuirks("pg").existence_check_sql("public.orders")
    assert "LIMIT 1" in sql
    assert "public.orders" in sql


def test_fk_reference_query_default_returns_none():
    q, params = BaseQuirks("pg").fk_reference_query("s", "t", "c")
    assert q is None
    assert params == []


def test_index_reference_query_default_returns_none():
    q, params = BaseQuirks("pg").index_reference_query("s", "t", "c")
    assert q is None
    assert params == []


# ---------------------------------------------------------------------------
# Per-DB overrides — introspector_class
# ---------------------------------------------------------------------------


def test_postgresql_introspector_class_returns_plugin_subclass():
    """F.3.a: PostgreSQL's quirks returns its plugin-located
    :class:`PostgreSQLIntrospector` (a thin :class:`SchemaIntrospector`
    subclass that lives in ``db/plugins/postgresql/introspection/``)."""
    from db.plugins.postgresql.introspection.postgresql_introspector import (
        PostgreSQLIntrospector,
    )
    from db.plugins.postgresql.quirks import PostgresqlQuirks

    assert PostgresqlQuirks().introspector_class() is PostgreSQLIntrospector


def test_oracle_introspector_class_returns_plugin_subclass():
    """F.3.e: Oracle's quirks returns its plugin-located :class:`OracleIntrospector`."""
    from db.plugins.oracle.introspection.oracle_introspector import OracleIntrospector
    from db.plugins.oracle.quirks import OracleQuirks

    assert OracleQuirks().introspector_class() is OracleIntrospector


def test_mysql_introspector_class_returns_plugin_subclass():
    """F.3.b: MySQL's quirks returns :class:`MySQLIntrospector`; MariaDB
    inherits this via :class:`MariadbQuirks(MysqlQuirks)`."""
    from db.plugins.mysql.introspection.mysql_introspector import MySQLIntrospector
    from db.plugins.mysql.quirks import MysqlQuirks

    assert MysqlQuirks().introspector_class() is MySQLIntrospector


def test_sqlserver_introspector_class_returns_plugin_subclass():
    """F.3.d: SQL Server's quirks returns its plugin-located :class:`SQLServerIntrospector`."""
    from db.plugins.sqlserver.introspection.sqlserver_introspector import SQLServerIntrospector
    from db.plugins.sqlserver.quirks import SqlserverQuirks

    assert SqlserverQuirks().introspector_class() is SQLServerIntrospector


def test_db2_introspector_class_returns_plugin_subclass():
    """F.3.f: DB2's quirks returns its plugin-located :class:`DB2Introspector`."""
    from db.plugins.db2.introspection.db2_introspector import DB2Introspector
    from db.plugins.db2.quirks import Db2Quirks

    assert Db2Quirks().introspector_class() is DB2Introspector


def test_cosmosdb_introspector_class():
    from db.plugins.cosmosdb.introspection import CosmosDbIntrospector
    from db.plugins.cosmosdb.quirks import CosmosdbQuirks as CosmosDbQuirks

    assert CosmosDbQuirks().introspector_class() is CosmosDbIntrospector


def test_sqlite_introspector_class():
    from db.plugins.sqlite.introspection import SQLiteIntrospector
    from db.plugins.sqlite.quirks import SqliteQuirks

    assert SqliteQuirks().introspector_class() is SQLiteIntrospector


# ---------------------------------------------------------------------------
# Per-DB overrides — non_transactional_sql_patterns
# ---------------------------------------------------------------------------


def test_postgresql_has_concurrently_pattern():
    from db.plugins.postgresql.quirks import PostgresqlQuirks

    patterns = [p for p, _ in PostgresqlQuirks().non_transactional_sql_patterns]
    assert any("CONCURRENTLY" in p for p in patterns)


def test_postgresql_has_vacuum_pattern():
    from db.plugins.postgresql.quirks import PostgresqlQuirks

    patterns = [p for p, _ in PostgresqlQuirks().non_transactional_sql_patterns]
    assert any("VACUUM" in p for p in patterns)


def test_sqlserver_has_fulltext_pattern():
    from db.plugins.sqlserver.quirks import SqlserverQuirks

    patterns = [p for p, _ in SqlserverQuirks().non_transactional_sql_patterns]
    assert any("FULLTEXT" in p for p in patterns)


def test_db2_no_non_transactional_patterns():
    from db.plugins.db2.quirks import Db2Quirks

    assert Db2Quirks().non_transactional_sql_patterns == ()


# ---------------------------------------------------------------------------
# Per-DB overrides — existence_check_sql
# ---------------------------------------------------------------------------


def test_oracle_existence_check_uses_rownum():
    from db.plugins.oracle.quirks import OracleQuirks

    sql = OracleQuirks().existence_check_sql('"HR"."ORDERS"')
    assert "ROWNUM" in sql
    assert "DUAL" in sql


def test_sqlserver_existence_check_uses_top():
    from db.plugins.sqlserver.quirks import SqlserverQuirks

    sql = SqlserverQuirks().existence_check_sql("[dbo].[orders]")
    assert "TOP 1" in sql


def test_postgresql_existence_check_uses_limit():
    from db.plugins.postgresql.quirks import PostgresqlQuirks

    sql = PostgresqlQuirks().existence_check_sql('"public"."orders"')
    assert "LIMIT 1" in sql


# ---------------------------------------------------------------------------
# Per-DB overrides — fk_reference_query
# ---------------------------------------------------------------------------


def test_postgresql_fk_query_returns_sql_and_params():
    from db.plugins.postgresql.quirks import PostgresqlQuirks

    sql, params = PostgresqlQuirks().fk_reference_query("myschema", "orders", "user_id")
    assert sql is not None
    assert "FOREIGN KEY" in sql.upper()
    assert params == ["myschema", "orders", "user_id"]


def test_oracle_fk_query_passes_schema_twice():
    from db.plugins.oracle.quirks import OracleQuirks

    sql, params = OracleQuirks().fk_reference_query("HR", "ORDERS", "USER_ID")
    assert sql is not None
    # OracleQuirks.fk_reference_bind_params returns [schema, schema, table, col]
    assert params == ["HR", "HR", "ORDERS", "USER_ID"]


def test_cosmosdb_fk_query_returns_none():
    from db.plugins.cosmosdb.quirks import CosmosdbQuirks as CosmosDbQuirks

    q, params = CosmosDbQuirks().fk_reference_query("s", "t", "c")
    assert q is None


def test_mysql_fk_query_returns_sql():
    from db.plugins.mysql.quirks import MysqlQuirks

    sql, params = MysqlQuirks().fk_reference_query("mydb", "orders", "user_id")
    assert sql is not None
    assert params == ["mydb", "orders", "user_id"]


def test_db2_fk_query_returns_sql():
    from db.plugins.db2.quirks import Db2Quirks

    sql, params = Db2Quirks().fk_reference_query("MYSCHEMA", "ORDERS", "USER_ID")
    assert sql is not None
    assert params == ["MYSCHEMA", "ORDERS", "USER_ID"]


def test_sqlserver_fk_query_returns_sql():
    from db.plugins.sqlserver.quirks import SqlserverQuirks

    sql, params = SqlserverQuirks().fk_reference_query("dbo", "orders", "user_id")
    assert sql is not None
    assert params == ["dbo", "orders", "user_id"]


# ---------------------------------------------------------------------------
# Per-DB overrides — index_reference_query
# ---------------------------------------------------------------------------


def test_mysql_index_query_returns_sql():
    from db.plugins.mysql.quirks import MysqlQuirks

    sql, params = MysqlQuirks().index_reference_query("mydb", "orders", "user_id")
    assert sql is not None
    assert "information_schema" in sql.lower()
    assert params == ["mydb", "orders", "user_id"]


def test_postgresql_index_query_returns_sql():
    from db.plugins.postgresql.quirks import PostgresqlQuirks

    sql, params = PostgresqlQuirks().index_reference_query("myschema", "orders", "user_id")
    assert sql is not None
    assert params == ["myschema", "orders", "user_id"]


# ---------------------------------------------------------------------------
# Story 2: IntrospectorFactory must be quirks-driven
# ---------------------------------------------------------------------------


def test_introspector_factory_uses_quirks():
    """``_register_defaults`` populates the dialect map from each
    quirks' ``introspector_class()``. F.3 wires every plugin to its
    own ``<D>Introspector`` subclass, so every supported dialect now
    appears in the map (no SchemaIntrospector fallback needed)."""
    from core.introspection.introspector_factory import IntrospectorFactory
    from db.plugins.cosmosdb.introspection import CosmosDbIntrospector
    from db.plugins.db2.introspection.db2_introspector import DB2Introspector
    from db.plugins.mysql.introspection.mysql_introspector import MySQLIntrospector
    from db.plugins.oracle.introspection.oracle_introspector import OracleIntrospector
    from db.plugins.postgresql.introspection.postgresql_introspector import (
        PostgreSQLIntrospector,
    )
    from db.plugins.sqlite.introspection import SQLiteIntrospector
    from db.plugins.sqlserver.introspection.sqlserver_introspector import SQLServerIntrospector

    IntrospectorFactory._DIALECT_MAP.clear()
    IntrospectorFactory._register_defaults()
    assert IntrospectorFactory._DIALECT_MAP.get("postgresql") is PostgreSQLIntrospector
    assert IntrospectorFactory._DIALECT_MAP.get("oracle") is OracleIntrospector
    assert IntrospectorFactory._DIALECT_MAP.get("mysql") is MySQLIntrospector
    assert IntrospectorFactory._DIALECT_MAP.get("mariadb") is MySQLIntrospector
    assert IntrospectorFactory._DIALECT_MAP.get("sqlserver") is SQLServerIntrospector
    assert IntrospectorFactory._DIALECT_MAP.get("db2") is DB2Introspector
    assert IntrospectorFactory._DIALECT_MAP.get("sqlite") is SQLiteIntrospector
    assert IntrospectorFactory._DIALECT_MAP.get("cosmosdb") is CosmosDbIntrospector


def test_introspector_factory_hardcoded_strings_absent():
    """_register_defaults must not import any DB module directly."""
    import inspect

    from core.introspection import introspector_factory

    src = inspect.getsource(introspector_factory.IntrospectorFactory._register_defaults)
    for dialect in ("postgresql", "oracle", "mysql", "sqlserver", "db2", "cosmosdb", "sqlite"):
        assert (
            f'"{dialect}"' not in src
        ), f"Hardcoded dialect '{dialect}' found in _register_defaults"


def test_sqlserver_tsql_aliases_resolve_non_transactional_patterns():
    """tsql / sql_server aliases must return SQL Server quirks, not BaseQuirks."""
    from db.provider_registry import ProviderRegistry

    for alias in ("tsql", "sql_server"):
        ProviderRegistry._quirks_cache.clear()  # force re-resolve
        quirks = ProviderRegistry.get_quirks(alias)
        patterns = [p for p, _ in quirks.non_transactional_sql_patterns]
        assert any(
            "FULLTEXT" in p for p in patterns
        ), f"alias '{alias}' returned BaseQuirks (no SQL Server patterns)"


def test_cosmosdb_aliases_resolve_is_nosql():
    """cosmos / nosql aliases must return CosmosDB quirks with is_nosql=True."""
    from db.provider_registry import ProviderRegistry

    for alias in ("cosmos", "nosql"):
        ProviderRegistry._quirks_cache.clear()  # force re-resolve
        quirks = ProviderRegistry.get_quirks(alias)
        assert quirks.is_nosql, f"alias '{alias}' returned BaseQuirks (is_nosql=False)"
