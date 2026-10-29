"""An empty undo script must refuse the whole batch before any undo work."""

import pytest
from sqlalchemy import create_engine, text

from dblift.api import DBLiftClient

pytest.importorskip("duckdb_engine")


@pytest.mark.unit
@pytest.mark.parametrize("dry_run", [False, True])
def test_comment_only_undo_refuses_whole_batch_before_callbacks(tmp_path, dry_run):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__first.sql").write_text("CREATE TABLE first_table (id INT);")
    (migrations / "V2__second.sql").write_text("CREATE TABLE second_table (id INT);")

    engine = create_engine(f"duckdb:///{tmp_path / 'db.duckdb'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))
    try:
        applied = client.migrate()
        assert applied.success, applied.error_message

        (migrations / "U2__second.sql").write_text("DROP TABLE second_table;")
        (migrations / "U1__first.sql").write_text("-- no executable SQL\n")
        (migrations / "beforeUndo__marker.sql").write_text("CREATE TABLE callback_marker (id INT);")

        result = client.undo(target_version="0", dry_run=dry_run)
    finally:
        client.close()

    with engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'")
            )
        }
    engine.dispose()

    assert result.success is False
    assert "U1__first.sql" in (result.error_message or "")
    assert not result.undone_migrations
    assert {"first_table", "second_table"} <= tables
    assert "callback_marker" not in tables
