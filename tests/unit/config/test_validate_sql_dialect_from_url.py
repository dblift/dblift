"""Regression test: ``validate-sql`` must infer the dialect from ``database.url``.

Root cause: ``_validate_sql_effective_dialect()`` (config/dblift_config.py) only
read ``database.type`` / ``--dialect``, never the ``database.url`` scheme, while
``BaseDatabaseConfig`` already infers the type from a URL scheme via
``_infer_type_from_url_scheme``. A config with only ``database.url:
sqlite:///...`` (no ``type:``) wrongly raised "validate-sql requires --dialect
for offline validation when no database type is configured."
"""

from argparse import Namespace
from pathlib import Path

import pytest

from dblift.config.dblift_config import load_config

pytestmark = [pytest.mark.unit]


def _validate_sql_args() -> Namespace:
    return Namespace(command="validate-sql", dialect=None)


def test_dialect_inferred_from_database_url_without_type(tmp_path: Path) -> None:
    """A config with database.url but no database.type must resolve the dialect."""
    config_file = tmp_path / "dblift.yml"
    config_file.write_text("database:\n  url: sqlite:///test.db\n")

    config = load_config(str(config_file), _validate_sql_args())

    assert config.database.type == "sqlite"
