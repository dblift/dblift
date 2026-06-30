"""Import Flyway command handler."""

from pathlib import Path
from typing import Any, Dict, List

from core.logger.results import OperationResult
from core.migration.commands.base_command import BaseCommand
from db.provider_registry import ProviderRegistry


class ImportFlywayCommand(BaseCommand):
    """Handles the import-flyway operation."""

    def execute(
        self,
        scripts_dir: Path,
        dry_run: bool = False,
        flyway_table: str = "flyway_schema_history",
    ) -> OperationResult:
        """Import migration history from Flyway.

        Args:
            scripts_dir: Directory containing migration scripts (accepted for interface compatibility,
            not used in this command — Flyway history is read directly from the database)
            dry_run: If True, only show what would be imported without actually importing
            flyway_table: Source Flyway schema history table name

        Returns:
            OperationResult with import status
        """
        result = OperationResult()
        result.target_schema = self.config.database.schema
        source_table = (flyway_table or "flyway_schema_history").strip()
        configured_target = getattr(self.config, "history_table", None)
        target_table = (
            configured_target.strip()
            if isinstance(configured_target, str) and configured_target.strip()
            else "dblift_schema_history"
        )

        # Populate database connection information
        self._populate_database_info(result)

        try:
            # Ensure schema and history table exist (this establishes the connection)
            self.history_manager.create_schema_and_history_table(create_schema=False)

            # Log command execution with connection info (after connection is established)
            self._log_command_header_update("import-flyway", dry_run=dry_run)

            # Read entries from the Flyway history table
            schema = self.config.database.schema

            # Distinguish "table missing" (configuration error) from "table empty"
            # (benign but still notable). get_applied_migrations silently returns
            # [] for both, so a user staring at "0 entries imported" cannot tell
            # whether their --db-url is pointing at the wrong database.
            if hasattr(self.provider, "table_exists") and not self.provider.table_exists(
                schema, source_table
            ):
                msg = (
                    f"{source_table} table not found in schema '{schema}'. "
                    "Verify the database connection points at a Flyway-managed schema, "
                    "or pass the correct --db-schema/--flyway-table."
                )
                self.log.error(msg)
                result.set_error(msg)
                self._log_command_completion("import-flyway", result)
                return result

            flyway_rows = self._get_flyway_rows(schema, source_table)

            if not flyway_rows:
                self.log.warning(f"{source_table} exists but contains no rows — nothing to import")
                result.message = f"0 entries imported from {source_table} (table empty)"
                result.complete()
                self._log_command_completion("import-flyway", result)
                return result

            rows_to_import, skipped_count = self._filter_existing_rows(
                schema, target_table, flyway_rows
            )

            # BUG-06: emit a user-visible preview in dry-run mode so callers
            # see the list of rows that would be written to dblift_schema_history
            # (previously only log.debug, invisible unless debug logging on).
            if dry_run:
                noun = "entry" if len(rows_to_import) == 1 else "entries"
                self.log.info(
                    f"DRY RUN: Would import {len(rows_to_import)} migration {noun} "
                    f"from {source_table}:"
                )
                for row in rows_to_import:
                    script = row.get("script", "<unknown>")
                    version = row.get("version", "")
                    checksum = row.get("checksum", "")
                    self.log.info(f"  - {script} (version: {version}, checksum: {checksum})")

            imported_count = 0
            for row in rows_to_import:
                if not dry_run:
                    self.provider.record_migration(schema, row, target_table)
                imported_count += 1

            if not dry_run and imported_count:
                commit = getattr(self.provider, "commit_transaction", None)
                if callable(commit):
                    commit()

            action = "would be imported" if dry_run else "imported"
            noun = "entry" if imported_count == 1 else "entries"
            result.message = f"{imported_count} {noun} {action} from {source_table}"
            if skipped_count:
                skip_noun = "duplicate" if skipped_count == 1 else "duplicates"
                result.message += f" ({skipped_count} {skip_noun} skipped)"
            result.complete()
            self._log_command_completion("import-flyway", result)
            return result

        except Exception as e:
            rollback = getattr(self.provider, "rollback_transaction", None)
            if callable(rollback):
                try:
                    rollback()
                except Exception as rollback_error:
                    self.log.debug(f"Rollback after import-flyway failure failed: {rollback_error}")
            self.log.error(f"Import Flyway operation failed: {e}")
            result.set_error(f"Import Flyway operation failed: {e}")
            self._log_command_completion("import-flyway", result)
            return result

    def _get_flyway_rows(self, schema: str, source_table: str) -> List[Dict[str, Any]]:
        db_type = str(getattr(self.config.database, "type", "") or "").lower()
        quirks = ProviderRegistry.get_quirks(db_type)
        if not quirks.flyway_source_table_case_sensitive:
            return self.provider.get_applied_migrations(schema, source_table)

        qualified_table = self.provider.get_schema_qualified_name(schema, source_table)
        query = f"""
        SELECT script, installed_rank, version, description,
               type, checksum, installed_by, installed_on,
               execution_time, success
        FROM {qualified_table}
        ORDER BY installed_rank
        """
        rows = self.provider.execute_query(query)
        return [self._normalize_flyway_row(row) for row in rows]

    def _filter_existing_rows(
        self, schema: str, target_table: str, flyway_rows: List[Dict[str, Any]]
    ) -> tuple[List[Dict[str, Any]], int]:
        existing_rows = self.provider.get_applied_migrations(schema, target_table)
        existing_versions = {
            str(row["version"]) for row in existing_rows if row.get("version") not in (None, "")
        }
        existing_scripts = {
            str(row["script"]) for row in existing_rows if row.get("script") not in (None, "")
        }

        rows_to_import = []
        skipped_count = 0
        for row in flyway_rows:
            version = row.get("version")
            script = row.get("script")
            duplicate_version = version not in (None, "") and str(version) in existing_versions
            duplicate_script = script not in (None, "") and str(script) in existing_scripts
            if duplicate_version or duplicate_script:
                skipped_count += 1
                continue
            rows_to_import.append(row)
        return rows_to_import, skipped_count

    @staticmethod
    def _normalize_flyway_row(row: Dict[str, Any]) -> Dict[str, Any]:
        fields = (
            "script",
            "installed_rank",
            "version",
            "description",
            "type",
            "checksum",
            "installed_by",
            "installed_on",
            "execution_time",
            "success",
        )

        def get_value(name: str) -> Any:
            return row.get(name, row.get(name.upper(), row.get(name.lower())))

        return {field: get_value(field) for field in fields}
