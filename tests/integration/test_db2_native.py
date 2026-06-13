"""Opt-in DB2 native SQLAlchemy smoke tests.

These tests require a DB2 container that is expected to run from a GitHub
Codespace. They stay skipped on local machines unless DBLIFT_TEST_DB2_URL is set.
"""

import os
import uuid

import pytest

from config import DbliftConfig
from config.database_config import Db2Config
from core.logger import NullLog
from db.plugins.db2.provider import Db2Provider

pytestmark = [pytest.mark.integration]


def test_db2_native_provider_connects_and_queries() -> None:
    url = os.environ.get("DBLIFT_TEST_DB2_URL")
    if not url:
        pytest.skip("Set DBLIFT_TEST_DB2_URL in a DB2 Codespace to run this smoke test")

    database = Db2Config(
        type="db2",
        url=url,
        username=os.environ.get("DBLIFT_TEST_DB2_USER"),
        password=os.environ.get("DBLIFT_TEST_DB2_PASSWORD"),
    )
    provider = Db2Provider(DbliftConfig(database=database), NullLog())

    schema = os.environ.get("DBLIFT_TEST_DB2_SCHEMA", "DBLIFT_SMOKE")
    table = f"SMOKE_{uuid.uuid4().hex[:8].upper()}"

    try:
        provider.create_schema_if_not_exists(schema)
        provider.execute_statement(f'CREATE TABLE "{schema}"."{table}" (ID INTEGER NOT NULL)')
        provider.execute_statement(f'INSERT INTO "{schema}"."{table}" (ID) VALUES (?)', params=[1])
        rows = provider.execute_query(f'SELECT ID FROM "{schema}"."{table}"')
        provider.execute_statement(f'DROP TABLE "{schema}"."{table}"')
    finally:
        provider.close()

    assert rows and (rows[0].get("ID") or rows[0].get("id")) == 1
