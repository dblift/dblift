"""An unclosed block comment is not skipped as comment-only: the engine's own error reaches the user."""

import pytest
from sqlalchemy import create_engine, text

from dblift.api import DBLiftClient

pytest.importorskip("duckdb_engine")

SCRIPT = "CREATE TABLE a (i int);\n/* forgot to close\nCREATE TABLE b (i int);\n"


def test_duckdb_migrate_fails_on_an_unclosed_block_comment(tmp_path):
    migrations = tmp_path / "m"
    migrations.mkdir()
    (migrations / "V1__t.sql").write_text(SCRIPT)
    engine = create_engine(f"duckdb:///{tmp_path / 'db.duckdb'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))
    try:
        result = client.migrate()
    finally:
        client.close()
    with engine.connect() as conn:
        tables = {r[0] for r in conn.execute(text("select table_name from information_schema.tables"))}
    engine.dispose()

    assert result.success is False
    assert "unterminated" in (result.error_message or "").lower()
    assert "a" not in tables
