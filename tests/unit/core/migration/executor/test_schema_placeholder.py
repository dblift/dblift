"""${dblift_schema} expands to the Oracle catalog spelling, quotes removed.

Unquoted ``myschema`` becomes ``MYSCHEMA``. Quoted ``"myschema"`` stays
``myschema``. Other dialects keep the configured text. A null schema stays
``None``.
"""

import pytest

from dblift.config.dblift_config import DbliftConfig
from dblift.core.logger import NullLog
from dblift.core.migration.executor.placeholder_manager import PlaceholderManager
from dblift.core.migration.placeholders.placeholder_service import PlaceholderService
from dblift.db.plugins.oracle.config import OracleConfig
from dblift.db.plugins.postgresql.config import PostgreSqlConfig

pytestmark = pytest.mark.unit


def _oracle(schema):
    config = DbliftConfig(
        database=OracleConfig(
            type="oracle",
            url="oracle+oracledb://localhost:1521/?service_name=FREEPDB1",
            username="system",
            password="oracle",
            schema=schema,
        )
    )
    return PlaceholderManager(config, NullLog()).init_placeholders()


def _replace(values, sql):
    return PlaceholderService(values, NullLog()).replace_placeholders(sql)


def test_oracle_unquoted_schema_is_the_uppercase_catalog_spelling():
    values = _oracle("myschema")
    assert values["dblift_schema"] == "MYSCHEMA"
    assert _replace(values, "${dblift_schema}.t") == "MYSCHEMA.t"
    assert _replace(values, '"${dblift_schema}"') == '"MYSCHEMA"'
    assert _replace(values, "'${dblift_schema}'") == "'MYSCHEMA'"


def test_oracle_quoted_schema_keeps_the_interior():
    values = _oracle('"myschema"')
    assert values["dblift_schema"] == "myschema"
    assert _replace(values, "${dblift_schema}.t") == "myschema.t"
    assert _replace(values, '"${dblift_schema}"') == '"myschema"'
    assert _replace(values, "'${dblift_schema}'") == "'myschema'"


def test_non_oracle_schema_placeholder_is_unchanged():
    config = DbliftConfig(
        database=PostgreSqlConfig(
            type="postgresql",
            url="postgresql+psycopg://localhost:5432/db",
            username="user",
            password="pass",
            schema="MySchema",
        )
    )
    values = PlaceholderManager(config, NullLog()).init_placeholders()
    assert values["dblift_schema"] == "MySchema"


def test_null_schema_placeholder_is_none():
    values = _oracle(None)
    assert values["dblift_schema"] is None
