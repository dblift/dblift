"""MySQL native-provider smoke tests."""

import uuid
from typing import Any

import pytest

from config import DbliftConfig
from db.plugins.mysql.config import MySqlConfig
from db.provider_registry import ProviderRegistry
from db.sqlalchemy_provider import SqlAlchemyProvider

pytestmark = pytest.mark.integration


def _mysql_config(mysql_container: dict[str, Any], database: str) -> DbliftConfig:
    db = MySqlConfig(
        type="mysql",
        host=mysql_container["host"],
        port=mysql_container["port"],
        database=database,
        username=mysql_container["username"],
        password=mysql_container["password"],
        schema=database,
    )
    return DbliftConfig(database=db)


def test_mysql_provider_is_native_sqlalchemy(mysql_container: dict[str, Any]) -> None:
    provider = ProviderRegistry.create_provider(
        _mysql_config(mysql_container, mysql_container["database"])
    )

    assert isinstance(provider, SqlAlchemyProvider)
    assert not hasattr(provider, "jvm_manager")


def test_mysql_native_roundtrip(mysql_container: dict[str, Any]) -> None:
    database = f"dblift_native_{uuid.uuid4().hex[:8]}"
    table = "roundtrip"
    bootstrap = ProviderRegistry.create_provider(
        _mysql_config(mysql_container, mysql_container["database"])
    )

    bootstrap.create_connection()
    try:
        bootstrap.execute_statement(f"CREATE DATABASE `{database}`")
        provider = ProviderRegistry.create_provider(_mysql_config(mysql_container, database))
        provider.create_connection()
        provider.execute_statement(
            f"CREATE TABLE `{database}`.`{table}` (id INT PRIMARY KEY, n TEXT)"
        )
        provider.execute_statement(f"INSERT INTO `{database}`.`{table}` VALUES (1, 'x')")

        rows = provider.execute_query(f"SELECT n FROM `{database}`.`{table}` WHERE id = 1")

        assert rows == [{"n": "x"}]
    finally:
        bootstrap.execute_statement(f"DROP DATABASE IF EXISTS `{database}`")
        if "provider" in locals():
            provider.close()
        bootstrap.close()


def test_mysql_native_introspects_tables_without_jdbc_metadata(
    mysql_container: dict[str, Any],
) -> None:
    from core.introspection.introspector_factory import IntrospectorFactory

    database = f"dblift_native_{uuid.uuid4().hex[:8]}"
    bootstrap = ProviderRegistry.create_provider(
        _mysql_config(mysql_container, mysql_container["database"])
    )

    bootstrap.create_connection()
    try:
        bootstrap.execute_statement(f"CREATE DATABASE `{database}`")
        provider = ProviderRegistry.create_provider(_mysql_config(mysql_container, database))
        provider.create_connection()
        provider.execute_statement(
            f"CREATE TABLE `{database}`.`users` "
            "(id INT PRIMARY KEY, email VARCHAR(255) NOT NULL UNIQUE)"
        )
        provider.execute_statement(
            f"CREATE VIEW `{database}`.`user_view` AS SELECT id FROM `{database}`.`users`"
        )
        provider.execute_statement(
            f"CREATE TABLE `{database}`.`dblift_schema_history` " "(installed_rank INT PRIMARY KEY)"
        )

        introspector = IntrospectorFactory.create(provider)
        tables = introspector.get_tables(database, table_pattern="user%")
        all_tables = introspector.get_tables(database, include_views=True)

        users = next(table for table in tables if table.name == "users")
        columns = {column.name: column for column in users.columns}

        assert columns["id"].is_primary_key is True
        assert columns["email"].nullable is False
        assert {table.name for table in tables} == {"users"}
        assert "dblift_schema_history" not in {table.name for table in all_tables}
        assert "user_view" in {table.name for table in all_tables}
    finally:
        bootstrap.execute_statement(f"DROP DATABASE IF EXISTS `{database}`")
        if "provider" in locals():
            provider.close()
        bootstrap.close()
