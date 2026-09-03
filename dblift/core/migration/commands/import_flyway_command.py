"""Import Flyway command handler."""

from pathlib import Path
from typing import Any, Dict, List

from dblift.core.logger.results import OperationResult
from dblift.core.migration.commands.base_command import BaseCommand
from dblift.core.migration.migration import MigrationType
from dblift.core.sql_validator._flyway_compatibility import FLYWAY_TYPE_TO_MIGRATION_TYPE
from dblift.db.object_naming import get_normalized_object_name
from dblift.db.provider_registry import ProviderRegistry


def _as_bool(value: Any) -> bool:
    """Read Flyway's ``success`` column as a real boolean.

    Flyway declares this column BOOLEAN on PostgreSQL but an integer type on
    MySQL and SQLite, and a hand-built table can hold the string "0". Our own
    PostgreSQL history column is BOOLEAN and psycopg refuses an int for it, so
    the value is normalised here rather than trusted as read.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "f", "n", "no")
    return bool(value)


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
        db_type = str(getattr(self.config.database, "type", "") or "").lower()
        if (
            source_table == default_source_table
            and ProviderRegistry.get_quirks(db_type).flyway_source_table_case_sensitive
        ):
            # No explicit --flyway-table override: normalize the default name to
            # the dialect's unquoted-identifier case so it matches a real Flyway
            # installation's table (e.g. Oracle/DB2 fold unquoted DDL to uppercase).
            source_table = get_normalized_object_name(source_table, db_type)
        configured_target = getattr(self.config, "history_table", None)
        target_table = (
            configured_target.strip()
            if isinstance(configured_target, str) and configured_target.strip()
            else "dblift_schema_history"
        )

        # Ensure the provider has a live connection before reading connection
        # metadata or querying the Flyway table — dry-run skips
        # create_schema_and_history_table below, which would otherwise be the
        # only thing establishing the connection for providers that need it.
        self._ensure_connected()

        # Populate database connection information
        self._populate_database_info(result)

        try:
            # Ensure schema and history table exist. Skipped in dry-run so no
            # table is created as a side effect.
            if not dry_run:
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

            # Map every row before writing any of them. ``_row_with_mapped_type``
            # raises on a Flyway type with no equivalent here, and that verdict
            # has to be reached in dry-run too — a dry run that reports success
            # for an import the real run refuses is worse than no dry run at
            # all. Doing it up front also means the refusal lands before the
            # first insert instead of partway through, so a rejected history
            # leaves the target table untouched rather than half-populated.
            mapped_rows = [self._row_with_mapped_type(row) for row in rows_to_import]

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
            for mapped_row in mapped_rows:
                if not dry_run:
                    self.provider.record_migration(schema, mapped_row, target_table)
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
        mapped_type = FLYWAY_TYPE_TO_MIGRATION_TYPE.get(str(flyway_type))  # lint: allow-enum-str
        if mapped_type is None:
            raise ValueError(
                f"Unrecognised Flyway migration type '{flyway_type}' for script "
                f"'{row.get('script')}': no mapping to a Dblift MigrationType is defined."
            )
        if mapped_type == MigrationType.SQL.name and not row.get("version"):
            # Flyway's convention for a repeatable migration is type=SQL with
            # no version — dblift models this as its own REPEATABLE type.
            mapped_type = MigrationType.REPEATABLE.name
        return {**row, "type": mapped_type, "success": _as_bool(row.get("success", True))}

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
