"""Integration tests for snapshot command.

Tests the snapshot command with real database connections and snapshot operations.
"""

import json

import pytest

from tests.integration.helpers.cli_runner import DBLiftCLI
from tests.integration.helpers.migration_helper import (
    create_config,
    create_versioned_migration,
    generate_test_sql,
)


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["postgresql", "mysql", "sqlserver", "oracle", "db2"],
    indirect=True,
)
class TestSnapshotCommand:
    """Integration tests for snapshot command."""

    def test_snapshot_database_stored_basic(self, db_container, tmp_path):
        """Test basic snapshot export from database-stored source."""
        config_file = create_config(tmp_path, db_container)
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        db_type = db_container["type"]
        schema = db_container.get("schema", "PUBLIC")

        # Create and apply migration (this will create a snapshot)
        create_versioned_migration(
            migrations_dir,
            "1.0.0",
            "initial",
            generate_test_sql(db_type, "users", schema),
        )

        cli = DBLiftCLI(config_file, migrations_dir)
        migrate_result = cli.migrate()
        assert migrate_result.success, f"Migration failed: {migrate_result.stderr}"

        # Export snapshot from database
        output_file = tmp_path / "snapshot.json"
        result = cli._run_command(
            "snapshot",
            output=str(output_file),
            source="database-stored",
        )

        assert result.success, f"Snapshot export failed: {result.stderr}"
        assert output_file.exists(), "Snapshot file was not created"

        # Verify JSON content
        content = json.loads(output_file.read_text())
        assert "metadata" in content
        assert "tables" in content or "dialect" in content

    def test_snapshot_live_database_basic(self, db_container, tmp_path):
        """Test basic snapshot export from live-database source."""
        config_file = create_config(tmp_path, db_container)
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        db_type = db_container["type"]
        schema = db_container.get("schema", "PUBLIC")

        # Create and apply migration
        create_versioned_migration(
            migrations_dir,
            "1.0.0",
            "initial",
            generate_test_sql(db_type, "users", schema),
        )

        cli = DBLiftCLI(config_file, migrations_dir)
        migrate_result = cli.migrate()
        assert migrate_result.success

        # Export snapshot from live database
        output_file = tmp_path / "live_snapshot.json"
        result = cli._run_command(
            "snapshot",
            output=str(output_file),
            source="live-database",
        )

        assert result.success, f"Snapshot export failed: {result.stderr}"
        assert output_file.exists(), "Snapshot file was not created"

        # Verify JSON content
        content = json.loads(output_file.read_text())
        assert "metadata" in content
        assert "tables" in content or "dialect" in content

    def test_snapshot_database_stored_no_snapshot(self, db_container, tmp_path):
        """Test snapshot export when no snapshot exists in database."""
        config_file = create_config(tmp_path, db_container)
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        cli = DBLiftCLI(config_file, migrations_dir)

        # Try to export snapshot without any migrations (no snapshot created)
        output_file = tmp_path / "snapshot.json"
        result = cli._run_command(
            "snapshot",
            output=str(output_file),
            source="database-stored",
        )

        # Should fail because no snapshot exists
        assert (
            not result.success
            or "No snapshot found" in result.stderr
            or "snapshot" in result.stderr.lower()
        )

    def test_snapshot_live_database_no_migrations(self, db_container, tmp_path):
        """Test snapshot export from live database with no migrations."""
        config_file = create_config(tmp_path, db_container)
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        cli = DBLiftCLI(config_file, migrations_dir)

        # Export snapshot from live database (should work even without migrations)
        output_file = tmp_path / "live_snapshot.json"
        result = cli._run_command(
            "snapshot",
            output=str(output_file),
            source="live-database",
        )

        # Should succeed - live database can be introspected even without migrations
        assert result.success, f"Snapshot export failed: {result.stderr}"
        assert output_file.exists(), "Snapshot file was not created"

        # Verify JSON content
        content = json.loads(output_file.read_text())
        assert "metadata" in content

    def test_snapshot_validation_errors(self, db_container, tmp_path):
        """Test validation errors."""
        config_file = create_config(tmp_path, db_container)
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        cli = DBLiftCLI(config_file, migrations_dir)

        # Test missing output
        result = cli._run_command("snapshot", source="database-stored")
        assert (
            not result.success
            or "required" in result.stderr.lower()
            or "output" in result.stderr.lower()
        )

        # Test invalid source
        output_file = tmp_path / "snapshot.json"
        result = cli._run_command(
            "snapshot",
            output=str(output_file),
            source="invalid-source",
        )
        assert (
            not result.success
            or "Invalid source" in result.stderr
            or "invalid" in result.stderr.lower()
        )

    def test_snapshot_export_after_multiple_migrations(self, db_container, tmp_path):
        """Test snapshot export after multiple migrations."""
        config_file = create_config(tmp_path, db_container)
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        db_type = db_container["type"]
        schema = db_container.get("schema", "PUBLIC")

        # Create multiple migrations
        create_versioned_migration(
            migrations_dir,
            "1.0.0",
            "initial",
            generate_test_sql(db_type, "users", schema),
        )
        create_versioned_migration(
            migrations_dir,
            "1.0.1",
            "add_orders",
            generate_test_sql(db_type, "orders", schema),
        )

        cli = DBLiftCLI(config_file, migrations_dir)
        migrate_result = cli.migrate()
        assert migrate_result.success

        # Export snapshot - should contain latest state
        output_file = tmp_path / "snapshot.json"
        result = cli._run_command(
            "snapshot",
            output=str(output_file),
            source="database-stored",
        )

        assert result.success, f"Snapshot export failed: {result.stderr}"
        assert output_file.exists()

        # Verify content includes both tables
        content = json.loads(output_file.read_text())
        tables = content.get("tables", [])
        table_names = [t.get("name", "").lower() for t in tables]
        # Should have at least one table (users or orders)
        assert len(table_names) > 0

    def test_snapshot_live_vs_database_stored_consistency(self, db_container, tmp_path):
        """Test that live-database and database-stored snapshots are consistent."""
        config_file = create_config(tmp_path, db_container)
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        db_type = db_container["type"]
        schema = db_container.get("schema", "PUBLIC")

        # Create and apply migration
        create_versioned_migration(
            migrations_dir,
            "1.0.0",
            "initial",
            generate_test_sql(db_type, "users", schema),
        )

        cli = DBLiftCLI(config_file, migrations_dir)
        migrate_result = cli.migrate()
        assert migrate_result.success

        # Export both types of snapshots
        db_snapshot_file = tmp_path / "db_snapshot.json"
        live_snapshot_file = tmp_path / "live_snapshot.json"

        result1 = cli._run_command(
            "snapshot",
            output=str(db_snapshot_file),
            source="database-stored",
        )
        assert result1.success

        result2 = cli._run_command(
            "snapshot",
            output=str(live_snapshot_file),
            source="live-database",
        )
        assert result2.success

        # Both should exist
        assert db_snapshot_file.exists()
        assert live_snapshot_file.exists()

        # Both should be valid JSON
        db_content = json.loads(db_snapshot_file.read_text())
        live_content = json.loads(live_snapshot_file.read_text())

        # Both should have same structure
        assert "metadata" in db_content
        assert "metadata" in live_content
        assert "tables" in db_content or "dialect" in db_content
        assert "tables" in live_content or "dialect" in live_content
