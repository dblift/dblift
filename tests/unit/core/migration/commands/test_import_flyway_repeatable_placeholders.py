"""Imported repeatables retain file identity and raw-content checksums."""

import zlib

from sqlalchemy import create_engine, text

from dblift.api import DBLiftClient
from dblift.api._engine_config import config_from_engine


def test_imported_repeatables_with_placeholders_are_not_reexecuted(tmp_path):
    scripts = tmp_path / "sql"
    scripts.mkdir()
    contents = {
        "R__1_create_user.sql": "INSERT INTO audit_log VALUES ('${username}');\n",
        "R__2_seed_data.sql": "INSERT INTO audit_log VALUES ('plain');\n",
    }
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE audit_log (name TEXT)"))
        connection.execute(text("""
            CREATE TABLE flyway_schema_history (
                installed_rank INTEGER PRIMARY KEY, version TEXT, description TEXT,
                type TEXT, script TEXT, checksum INTEGER, installed_by TEXT,
                installed_on TEXT, execution_time INTEGER, success INTEGER
            )
        """))
        for rank, (script, content) in enumerate(contents.items(), 1):
            (scripts / script).write_text(content)
            checksum = zlib.crc32(content.rstrip("\n").encode())
            if checksum >= 2**31:
                checksum -= 2**32
            connection.execute(
                text("""
                INSERT INTO flyway_schema_history VALUES
                (:rank, NULL, :description, 'SQL', :script, :checksum,
                 'flyway', '2026-09-01 00:00:00', 0, 1)
            """),
                {
                    "rank": rank,
                    "description": script[3:-4].replace("_", " "),
                    "script": script,
                    "checksum": checksum,
                },
            )
    config = config_from_engine(engine, migrations_dir=scripts)
    config.placeholders = {"username": "alice"}
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=scripts, config=config)
    try:
        imported = client.import_flyway()
        assert imported.success, imported.error_message
        info = client.info()
        assert info.success, info.error_message
        assert info.pending_count == 0
        assert len(info.applied_migrations) == 2
        for _ in range(2):
            result = client.migrate()
            assert result.success, result.error_message
            assert result.migrations == []
        assert client.provider.execute_query("SELECT * FROM audit_log") == []
        (scripts / "R__1_create_user.sql").write_text(
            contents["R__1_create_user.sql"] + "-- changed\n"
        )
        changed = client.migrate()
        assert changed.success, changed.error_message
        assert len(changed.migrations) == 1
        assert client.migrate().migrations == []
        rows = client.provider.execute_query("SELECT * FROM audit_log")
        assert rows == [{"name": "alice"}]
    finally:
        client.close()
        engine.dispose()
