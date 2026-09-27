"""Import Flyway command handler."""

from pathlib import Path
from typing import Any, Dict, List

from dblift.core.constants import DEFAULT_HISTORY_TABLE
from dblift.core.logger.results import OperationResult
from dblift.core.migration.commands.base_command import BaseCommand
from dblift.core.migration.migration import success_to_bool
from dblift.core.sql_validator._flyway_compatibility import dblift_type_for_flyway_row


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
        default_source_table = "flyway_schema_history"
        source_table = (flyway_table or default_source_table).strip()
        configured_target = getattr(self.config, "history_table", None)
        target_table = (
            configured_target.strip()
            if isinstance(configured_target, str) and configured_target.strip()
            else DEFAULT_HISTORY_TABLE
        )

        # Connect, create the schema-history table (skipped in dry-run so no
        # table is created as a side effect) and read connection metadata.
        # Failures raise PreflightConnectionError, as for every other command.
        self._run_preflight(result, ensure_history=True, dry_run=dry_run)

        try:
            if not dry_run:
                self.state_manager.new_read_snapshot()

            # Log command execution with connection info (after connection is established)
            self._log_command_header_update("import-flyway", dry_run=dry_run)

            # Read entries from the Flyway history table
            schema = self.config.database.schema
            source_table = self.state_manager.resolve_flyway_source_table(schema, source_table)

            # Distinguish "table missing" (configuration error) from "table empty"
            # (benign but still notable). get_applied_migrations silently returns
            # [] for both, so a user staring at "0 entries imported" cannot tell
            # whether their --db-url is pointing at the wrong database.
            if not self.state_manager.history_source_exists(schema, source_table):
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

            # Map every row before writing any of them. ``_row_with_mapped_type``
            # raises on a Flyway type with no equivalent here, and that verdict
            # has to be reached in dry-run too — a dry run that reports success
            # for an import the real run refuses is worse than no dry run at
            # all. Doing it up front also means the refusal lands before the
            # first insert instead of partway through, so a rejected history
            # leaves the target table untouched rather than half-populated.
            mapped_rows = [self._row_with_mapped_type(row) for row in rows_to_import]

            # Emit a user-visible preview in dry-run mode so callers
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
            for mapped_row in mapped_rows:
                if not dry_run:
                    self.provider.record_migration(schema, mapped_row, target_table)
                imported_count += 1

            if not dry_run and imported_count:
                commit = getattr(self.provider, "commit_transaction", None)
                if callable(commit):
                    commit()
                self.state_manager.new_read_snapshot()

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
        return self.state_manager.read_history_rows(schema, source_table, flyway_source=True)

    def _filter_existing_rows(
        self, schema: str, target_table: str, flyway_rows: List[Dict[str, Any]]
    ) -> tuple[List[Dict[str, Any]], int]:
        existing_rows = self.state_manager.read_history_rows(schema, target_table)
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

    def _row_with_mapped_type(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy of ``row`` with Flyway's ``type`` vocabulary translated to a Dblift ``MigrationType`` member name.

        Flyway writes values like ``JDBC``/``SPRING_JDBC``/``SCRIPT`` that are
        not Dblift ``MigrationType`` members. Writing them verbatim would
        later read back as ``MigrationType.UNKNOWN`` (see
        ``AppliedMigration.from_history_row``), which is not a versioned
        type, so ``migrate`` would re-offer and re-execute an already-applied
        script. Raises if a type has no defined mapping, so the import aborts
        loudly instead of writing a value that would silently degrade.

        A row with no ``type`` value at all is left untouched rather than
        raising: real Flyway rows always populate this column, so an absent
        value means the caller isn't describing genuine Flyway vocabulary
        (e.g. a partial row from another code path) rather than an
        unrecognised one.
        """
        flyway_type = row.get("type")
        if not flyway_type:
            return dict(row)
        # ``flyway_type`` is a raw column value from Flyway's own history
        # table (e.g. "SQL", "JDBC"), never a MigrationType member — the
        # str() is defensive against non-text column types, not an enum cast.
        mapped_type = dblift_type_for_flyway_row(
            str(flyway_type), row.get("version")  # lint: allow-enum-str
        )
        if mapped_type is None:
            raise ValueError(
                f"Unrecognised Flyway migration type '{flyway_type}' for script "
                f"'{row.get('script')}': no mapping to a Dblift MigrationType is defined."
            )
        return {**row, "type": mapped_type, "success": success_to_bool(row.get("success", True))}
