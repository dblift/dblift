"""Alpha notices stay on direct legacy use, away from canonical SQL paths."""

from __future__ import annotations

import warnings

import pytest
from sqlalchemy import create_engine

from dblift.api.client import DBLiftClient
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.statement import execution_strings


@pytest.mark.parametrize(
    "dialect",
    [
        "sqlite",
        "postgresql",
        "cockroachdb",
        "redshift",
        "mysql",
        "mariadb",
        "oracle",
        "sqlserver",
        "db2",
        "duckdb",
        "snowflake",
    ],
)
def test_canonical_splitter_has_no_deprecation_warning(dialect: str) -> None:
    script = "SELECT 1\nGO\nSELECT 2\nGO\n" if dialect == "sqlserver" else "SELECT 1;\nSELECT 2;\n"
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        splitter = StatementSplitter(dialect)
        records = splitter.split(script)
        strings = splitter.split_statements(script)
    assert strings == execution_strings(records)
    assert len(strings) == 2


def test_canonical_sqlite_migrate_and_info_have_no_deprecation_warning(tmp_path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__alpha_notice.sql").write_text("CREATE TABLE alpha_notice (id INT);")
    engine = create_engine(f"sqlite:///{tmp_path / 'alpha_notice.db'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            before = client.info()
            migrated = client.migrate()
            after = client.info()
        assert before.success
        assert migrated.success
        assert after.success
    finally:
        client.close()
        engine.dispose()
