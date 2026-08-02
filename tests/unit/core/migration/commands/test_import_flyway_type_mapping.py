"""``import-flyway`` must not write Flyway's own ``type`` vocabulary verbatim.

Flyway's ``flyway_schema_history.type`` column uses its own vocabulary
(``SQL``, ``JDBC``, ``SPRING_JDBC``, ``SCRIPT``, ``BASELINE``, ``UNDO_SQL``, ...).
Most of those names are not members of Dblift's ``MigrationType`` enum. Before
this fix, ``ImportFlywayCommand`` copied the column straight into
``dblift_schema_history`` (see ``_normalize_flyway_row`` /
``provider.record_migration``). On the next read, ``AppliedMigration.from_history_row``
looks the stored string up by exact member name and silently falls back to
``MigrationType.UNKNOWN`` for anything it doesn't recognise. ``UNKNOWN`` is not
a versioned type, so the imported row stopped counting as applied and
``migrate`` re-ran a migration a real Flyway installation had already
executed against the live schema — a live data-loss bug, not just a cosmetic
read-back issue.

This test reproduces the exact scenario end to end against a real SQLite
database (no mocks): a Flyway history row typed ``JDBC`` — Flyway's type for
a versioned migration executed through a JDBC-based migration resolver, not
a plain ``.sql`` script — is imported, and ``migrate`` must treat it as
already applied rather than re-executing the script.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from api import DBLiftClient
from core.migration.migration import MigrationType, calculate_migration_script_checksum

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]

_SCRIPT_CONTENT = "CREATE TABLE t (id INTEGER PRIMARY KEY);\n"

# The checksum a real Flyway installation would have recorded for
# ``_SCRIPT_CONTENT`` — dblift's own checksum function is documented as
# "Flyway-compatible" (see ``MigrationScriptManager.calculate_checksum``),
# so this is what a genuine Flyway row for this script looks like, not a
# stand-in value.
_SCRIPT_CHECKSUM = calculate_migration_script_checksum(_SCRIPT_CONTENT)


def _seed_flyway_history(
    engine: Any,
    *,
    migration_type: str,
    version: "str | None" = "1",
    script: str = "V1__a.sql",
) -> None:
    """Create a table Flyway already migrated, plus its own history row.

    Mirrors what a real Flyway installation leaves behind: the schema change
    already applied, and a ``flyway_schema_history`` row describing it with
    Flyway's own ``type`` vocabulary. ``version`` defaults to a versioned
    migration's Flyway convention; pass ``None`` to mirror Flyway's own
    convention for a repeatable migration.
    """
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
        conn.execute(text("""
                CREATE TABLE flyway_schema_history (
                    installed_rank INTEGER PRIMARY KEY,
                    version TEXT,
                    description TEXT,
                    type TEXT,
                    script TEXT,
                    checksum INTEGER,
                    installed_by TEXT,
                    installed_on TEXT,
                    execution_time INTEGER,
                    success INTEGER
                )
                """))
        conn.execute(
            text("""
                INSERT INTO flyway_schema_history
                (installed_rank, version, description, type, script, checksum,
                 installed_by, installed_on, execution_time, success)
                VALUES (1, :version, 'a', :type, :script, :checksum, 'flyway',
                        '2026-01-01 00:00:00', 0, 1)
                """),
            {
                "type": migration_type,
                "checksum": _SCRIPT_CHECKSUM,
                "version": version,
                "script": script,
            },
        )


def _make_client(
    tmp_path: Path, *, migration_type: str = "JDBC", version: "str | None" = "1", script: str = "V1__a.sql"
) -> "DBLiftClient":
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / script).write_text(_SCRIPT_CONTENT)

    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    _seed_flyway_history(engine, migration_type=migration_type, version=version, script=script)
    return DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations_dir))


class TestImportFlywayJdbcTypeMapping:
    def test_imported_jdbc_row_is_not_reoffered_as_pending(self, tmp_path: Path) -> None:
        """The reported scenario: import a JDBC-typed row, then migrate.

        Before the fix this re-executes ``V1__a.sql`` against a schema that
        already has it applied — here that surfaces as ``migrate`` failing
        with "table t already exists", because the CREATE TABLE the row
        already covers runs a second time. After the fix ``migrate`` finds
        nothing pending and touches nothing.
        """
        client = _make_client(tmp_path)

        import_result = client.import_flyway()
        assert import_result.success is True

        migrate_result = client.migrate()

        assert migrate_result.success is True, migrate_result.error_message
        assert migrate_result.migrations == []

    def test_imported_row_stores_a_recognised_dblift_migration_type(self, tmp_path: Path) -> None:
        """The write path must not persist Flyway's raw ``JDBC`` vocabulary.

        Pinned directly against the stored column (not just the
        ``migrate`` behaviour above) so a regression here is caught even if
        some other change accidentally masks the re-execution symptom.
        """
        client = _make_client(tmp_path)

        client.import_flyway()

        rows = client.provider.execute_query(
            "SELECT script, type FROM dblift_schema_history WHERE script = ?",
            ["V1__a.sql"],
        )
        assert len(rows) == 1
        assert rows[0]["type"] == "SQL"


class TestImportFlywayRepeatableTypeMapping:
    """Flyway's own convention for a repeatable migration is ``type=SQL`` with
    no ``version`` — not a distinct ``type`` value. Before this fix,
    ``_row_with_mapped_type`` sent every ``type=SQL`` Flyway row straight to
    Dblift's own ``SQL`` type regardless of ``version``, so a repeatable row
    was imported as if it were versioned, and ``info`` displayed it under
    "Versioned" instead of "Repeatable".
    """

    def test_versionless_sql_row_maps_to_repeatable(self, tmp_path: Path) -> None:
        client = _make_client(
            tmp_path, migration_type="SQL", version=None, script="R__refresh_view.sql"
        )

        import_result = client.import_flyway()
        assert import_result.success is True

        rows = client.provider.execute_query(
            "SELECT script, type FROM dblift_schema_history WHERE script = ?",
            ["R__refresh_view.sql"],
        )
        assert len(rows) == 1
        assert rows[0]["type"] == MigrationType.REPEATABLE.name

    def test_versioned_sql_row_still_maps_to_sql(self, tmp_path: Path) -> None:
        """A genuinely versioned ``type=SQL`` row must still map to ``SQL``,
        not be swept up by the version-less-repeatable override."""
        client = _make_client(
            tmp_path, migration_type="SQL", version="1", script="V1__a.sql"
        )

        import_result = client.import_flyway()
        assert import_result.success is True

        rows = client.provider.execute_query(
            "SELECT script, type FROM dblift_schema_history WHERE script = ?",
            ["V1__a.sql"],
        )
        assert len(rows) == 1
        assert rows[0]["type"] == MigrationType.SQL.name
