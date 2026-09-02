"""Regression test for issue #825.

``validate-sql --dialect X`` (no ``--config``/``--db-url``) must resolve a
fully offline config, matching the flag's own ``--help`` text ("defaults to
dialect from database config").

Root cause: ``_validate_sql_lint_filler()`` (config/dblift_config.py) builds
a placeholder ``database:`` block from ``quirks.lint_placeholder_url``, which
was ``None`` for every plugin — so the filler came back empty and
``load_config`` fell through to "No configuration source provided" instead
of running the offline lint path.
"""

from argparse import Namespace

import pytest

from dblift.config.dblift_config import load_config
from dblift.config.errors import ConfigurationError

pytestmark = [pytest.mark.unit]


def _validate_sql_args(dialect: str) -> Namespace:
    return Namespace(command="validate-sql", dialect=dialect)


@pytest.mark.parametrize(
    "dialect,url_prefix",
    [
        ("sqlite", "sqlite://"),
        ("duckdb", "duckdb://"),
        ("postgresql", "postgresql://"),
        ("mysql", "mysql://"),
        ("mariadb", "mysql://"),  # MariaDB shares MySQL's config class / URL scheme
        ("cockroachdb", "postgresql://"),  # PG-wire compatible, inherits PostgresqlQuirks
        ("citus", "postgresql://"),  # built via make_pg_compatible_plugin
        ("oracle", "oracle://"),
        ("sqlserver", "mssql://"),
        ("db2", "db2://"),
    ],
)
def test_dialect_only_resolves_offline_without_config_or_db_url(
    dialect: str, url_prefix: str
) -> None:
    """--dialect alone (no --config/--db-url) must not raise ConfigurationError."""
    config = load_config(None, _validate_sql_args(dialect))
    assert config.database.type == dialect
    assert config.database.url.startswith(url_prefix)


def test_cosmosdb_dialect_alone_still_requires_config() -> None:
    """CosmosDB has no SQL parser (CosmosdbQuirks.parser_class returns None for
    every parser_type) so offline SQL lint cannot apply; --dialect cosmosdb
    alone still needs --config/--db-url, same as before this fix."""
    with pytest.raises(ConfigurationError):
        load_config(None, _validate_sql_args("cosmosdb"))


def test_no_dialect_and_no_config_still_raises() -> None:
    """Sanity check: the offline path is gated on --dialect, not a blanket bypass."""
    with pytest.raises(ConfigurationError):
        load_config(None, Namespace(command="validate-sql"))
