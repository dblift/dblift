"""Regression tests for CosmosDB container name parsing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.sql_generator.sql_statement import SqlStatement
from db.plugins.cosmosdb.cosmosdb.query_executor import CosmosDbQueryExecutor
from db.plugins.cosmosdb.sdk_translator import CosmosDbSdkTranslator

pytestmark = [pytest.mark.unit]


def test_create_container_if_not_exists_parses_actual_container_name():
    executor = CosmosDbQueryExecutor(connection_manager=MagicMock())

    container_name = executor._parse_container_name(
        "CREATE CONTAINER IF NOT EXISTS config WITH PARTITION KEY /id;"
    )

    assert container_name == "config"


def test_drop_container_if_exists_parses_actual_container_name():
    translator = CosmosDbSdkTranslator()
    statement = SqlStatement(
        sql="DROP CONTAINER IF EXISTS config;",
        statement_type="DROP",
        object_type="CONTAINER",
        object_name="",
        dialect="cosmosdb",
        requires_sdk=True,
    )

    operation = translator.translate_to_sdk_operation(statement)

    assert operation is not None
    assert operation["container_name"] == "config"


def test_create_container_if_not_exists_undo_uses_actual_container_name():
    translator = CosmosDbSdkTranslator()
    statement = SqlStatement(
        sql="CREATE CONTAINER IF NOT EXISTS config WITH PARTITION KEY /id;",
        statement_type="CREATE",
        object_type="CONTAINER",
        object_name="config",
        dialect="cosmosdb",
    )

    undo = translator.generate_undo_script([statement])

    assert "DROP CONTAINER config;" in undo
    assert "DROP CONTAINER IF;" not in undo
