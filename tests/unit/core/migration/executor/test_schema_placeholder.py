"""${dblift_schema} expands to the configured name with quotes removed.

An unquoted value is not uppercased. A double-quoted Oracle schema
``"myschema"`` therefore still reaches that user from ``"${dblift_schema}"``,
which is how 4.8.0 scripts were written.
"""

import pytest

from dblift.config.dblift_config import DbliftConfig
from dblift.core.logger import NullLog
from dblift.core.migration.executor.placeholder_manager import PlaceholderManager
from dblift.core.migration.placeholders.placeholder_service import PlaceholderService
from dblift.db.plugins.oracle.config import OracleConfig

pytestmark = pytest.mark.unit


def _placeholders(schema: str) -> dict:
    config = DbliftConfig(
        database=OracleConfig(
            type="oracle",
            url="oracle+oracledb://localhost:1521/?service_name=FREEPDB1",
            username="system",
            password="oracle",
            schema=schema,
        )
    )
    values = PlaceholderManager(config, NullLog()).init_placeholders()
    return values


def test_quoted_schema_placeholder_keeps_interior_case():
    service = PlaceholderService(_placeholders('"myschema"'), NullLog())
    assert service.replace_placeholders("${dblift_schema}.t") == "myschema.t"
    assert service.replace_placeholders('"${dblift_schema}"') == '"myschema"'
    assert service.replace_placeholders("'${dblift_schema}'") == "'myschema'"


def test_unquoted_schema_placeholder_is_not_uppercased():
    values = _placeholders("myschema")
    assert values["dblift_schema"] == "myschema"
