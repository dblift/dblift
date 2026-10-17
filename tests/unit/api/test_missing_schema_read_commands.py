"""Reading an unmigrated target schema must not initialize database objects."""

import duckdb
import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("command,dry_run", [("info", False), ("undo", False), ("undo", True)])
def test_missing_schema_reads_empty_history_without_ddl(tmp_path, command, dry_run):
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    (scripts / "V1__create_items.sql").write_text("CREATE TABLE items (id INTEGER);")
    (scripts / "U1__drop_items.sql").write_text("DROP TABLE items;")
    database = tmp_path / "database.duckdb"
    config = DbliftConfig.from_dict(
        {
            "database": {"type": "duckdb", "url": f"duckdb:///{database}", "schema": "app"},
            "migrations": {"directory": str(scripts)},
        }
    )

    with DBLiftClient.from_config(config) as client:
        result = client.info() if command == "info" else client.undo(dry_run=dry_run)

    assert result.success, result.error_message
    if command == "info":
        assert [(row.version, row.status) for row in result.migrations] == [("1", "PENDING")]
    else:
        assert not result.migrations
    with duckdb.connect(str(database)) as connection:
        assert (
            connection.execute(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'app'"
            ).fetchall()
            == []
        )
        assert (
            connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name = 'dblift_schema_history'"
            ).fetchall()
            == []
        )
