"""
Repair command implementation.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    pass

from core.exceptions import ExecutionError
from core.logger.results import RepairResult
from core.migration._type_match import is_migration_type
from core.migration.migration import Migration
from core.migration.state.migration_state import MigrationState
from db.provider_capabilities import ensure_provider_connection
from db.provider_interfaces import TransactionalProvider

from .base_command import BaseCommand


class RepairSafetyError(Exception):
    """Raised when a repair operation would make a dangerous bulk change.

    Specifically: when the scripts directory is empty (or unreadable) but
    the history table has applied migrations that would all be converted
    to DELETE entries. Almost always a misconfigured ``--scripts`` or an
    operator pointing at the wrong repo — silently marking every applied
    migration as deleted is not a recoverable mistake, so the command
    refuses and asks the operator to confirm the directory.
    """


def _count_candidate_missing(applied_migrations: Any, deleted_scripts: Set[str]) -> int:
    """Count applied migrations that would be flagged MISSING_SCRIPT.

    Mirrors the filter the main loop applies: skip DELETE-type entries and
    scripts already recorded as deleted. Used by the empty-filesystem
    safety gate so the error message reports the number of rows the user
    is being protected from.
    """
    count = 0
    for applied in applied_migrations:
        script_name = getattr(applied, "script_name", "")
        if not script_name:
            continue
        migration_type = getattr(applied, "type", None)
        if (
            migration_type
            and hasattr(migration_type, "name")
            and migration_type.name
            in (
                "DELETE",
                "BASELINE",
            )
        ):
            continue
        if isinstance(migration_type, str) and migration_type.upper() in ("DELETE", "BASELINE"):
            continue
        if script_name in deleted_scripts:
            continue
        count += 1
    return count


class RepairCommand(BaseCommand):
    """Handles the 'repair' command execution."""

    def execute(
        self,
        scripts_dir: Path,
        dry_run: bool = False,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
    ) -> RepairResult:
        """Repair migration history by fixing checksums and removing invalid entries."""
        result = RepairResult()
        result.target_schema = self.config.database.schema

        # Populate database connection information
        self._populate_database_info(result)

        try:
            # Ensure schema and history table exist (this establishes the connection)
            self.history_manager.create_schema_and_history_table(create_schema=False)

            # Log command execution with connection info (after connection is established)
            self._log_command_header_update("repair", dry_run=dry_run)

            # Build migration state
            migration_state = self._build_migration_state(
                scripts_dir,
                recursive=recursive,
                additional_dirs=additional_dirs,
                dir_recursive_map=dir_recursive_map,
            )

            # Collect all repairs needed
            repairs_needed: List[Dict[str, Any]] = []
            repairs_needed.extend(self._detect_checksum_changes(migration_state))
            repairs_needed.extend(
                self._detect_missing_migrations(
                    migration_state,
                    scripts_dir,
                    recursive=recursive,
                    additional_dirs=additional_dirs,
                    dir_recursive_map=dir_recursive_map,
                )
            )
            repairs_needed.extend(
                self._detect_checksum_drift(
                    migration_state,
                    repairs_needed,
                    scripts_dir,
                    recursive=recursive,
                    additional_dirs=additional_dirs,
                    dir_recursive_map=dir_recursive_map,
                )
            )

            if not repairs_needed:
                self.log.info(
                    "Repair check completed: no checksum, failed migration, or history issues detected."
                )
                self._log_command_completion("repair", result)
                return result

            if dry_run:
                self.log.info("DRY RUN: the following repairs would be executed:")
                for repair in repairs_needed:
                    self.log.info(f"  - {repair['type']}: {repair['script']}")
                self._log_command_completion("repair", result)
                return result

            # Execute repairs
            repairs_executed, error = self._execute_repair_loop(
                repairs_needed, result, migration_state
            )
            if error:
                self._log_command_completion("repair", result)
                return result

            # Post-repair validation
            if repairs_executed:
                validation_error = self._validate_post_repair_state(
                    migration_state=migration_state,
                    repairs_needed=repairs_needed,
                    scripts_dir=scripts_dir,
                    recursive=recursive,
                    additional_dirs=additional_dirs,
                    dir_recursive_map=dir_recursive_map,
                    result=result,
                )
                if validation_error:
                    self._log_command_completion("repair", result)
                    return result

            # Log summary
            self._build_repair_summary(result)

            self._log_command_completion("repair", result)
            return result

        except RepairSafetyError as e:
            # Operator-facing safety abort — not a crash. Log the exact
            # message (already actionable) without stack-trace noise.
            self.log.error(str(e))
            result.set_error(str(e))
            self._log_command_completion("repair", result)
            return result
        except Exception as e:
            self.log.error(f"Repair operation failed: {e}")
            result.set_error(f"Repair operation failed: {e}")
            self._log_command_completion("repair", result)
            return result

    def _build_migration_state(
        self,
        scripts_dir: Path,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
    ) -> MigrationState:
        """Build the migration state object, returning an empty state on failure.

        Args:
            scripts_dir: Directory containing migration scripts
            recursive: Whether to scan directories recursively
            additional_dirs: Additional directories to scan
            dir_recursive_map: Per-directory recursive override map

        Returns:
            MigrationState instance (empty if build fails)
        """
        try:
            return self.state_manager.build_state(
                scripts_dir,
                recursive=recursive,
                additional_dirs=additional_dirs,
                dir_recursive_map=dir_recursive_map,
            )
        except Exception as e:
            # If build_state fails (e.g., due to mocked dependencies in tests), create empty state
            self.log.debug(f"Could not build migration state: {e}")
            return MigrationState()

    def _detect_checksum_changes(self, migration_state: MigrationState) -> List[Dict[str, Any]]:
        """Build repair entries for checksum changes reported by the state manager.

        Args:
            migration_state: Current migration state

        Returns:
            List of CHECKSUM_MISMATCH repair dicts from state manager
        """
        repairs: List[Dict[str, Any]] = []
        for change in getattr(migration_state, "checksum_changes", []):
            repairs.append(
                {
                    "type": "CHECKSUM_MISMATCH",
                    "script": change.script_name,
                    "old_checksum": change.previous_checksum,
                    "new_checksum": change.current_checksum,
                }
            )
        return repairs

    def _detect_missing_migrations(
        self,
        migration_state: MigrationState,
        scripts_dir: Path,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
    ) -> List[Dict[str, Any]]:
        """Detect missing migrations (applied but script file no longer exists) and failed migrations.

        Args:
            migration_state: Current migration state
            scripts_dir: Directory containing migration scripts
            recursive: Whether to scan directories recursively
            additional_dirs: Additional directories to scan
            dir_recursive_map: Per-directory recursive override map

        Returns:
            List of MISSING_SCRIPT and FAILED_MIGRATION repair dicts
        """
        repairs: List[Dict[str, Any]] = []

        applied_migrations = getattr(migration_state, "applied_objects", [])
        deleted_scripts: Set[str] = getattr(migration_state, "deleted_scripts", set())

        # Load filesystem scripts. A load failure (permission denied, missing
        # directory not caught by the CLI layer, malformed script) propagates
        # — silently falling back to an empty set turned this into a
        # mass-mark-missing footgun (BUG-04). The CLI has already verified
        # that the directory exists for every command except ``baseline``;
        # anything that raises here is the operator's to fix before repair
        # can proceed safely.
        filesystem_migrations = self.script_manager.load_migration_scripts(
            scripts_dir,
            recursive=recursive,
            additional_dirs=additional_dirs,
            dir_recursive_map=dir_recursive_map,
        )
        filesystem_scripts: Set[str] = set()
        for migration_group in filesystem_migrations.values():
            for migration in migration_group:
                filesystem_scripts.add(getattr(migration, "script_name", ""))

        # Safety gate: if the filesystem produced zero scripts but the
        # history has applied migrations that would all be marked MISSING,
        # refuse — this is almost always a misconfigured ``--scripts`` or
        # empty default ``./migrations`` directory (BUG-04). Without this
        # guard, a single ``repair`` invocation without ``--dry-run`` would
        # convert every applied migration into a DELETE entry.
        if not filesystem_scripts:
            candidate_missing_count = _count_candidate_missing(applied_migrations, deleted_scripts)
            if candidate_missing_count > 0:
                raise RepairSafetyError(
                    f"Refusing to mark {candidate_missing_count} applied migration(s) "
                    f"as missing: no migration scripts found in {scripts_dir}. "
                    "Pass --scripts <dir> pointing to your migration files, or "
                    "verify that the configured directory contains at least one "
                    "matching file before retrying."
                )

        # Find migrations in history but not in filesystem
        for applied in applied_migrations:
            script_name = getattr(applied, "script_name", "")
            if not script_name:
                continue

            migration_type = getattr(applied, "type", None)

            # Skip DELETE and BASELINE type migrations. BASELINE rows (e.g. the
            # synthetic ``B2__.sql`` marker written by ``baseline``) never have
            # a matching filesystem script by design — flagging them as missing
            # produces noisy false positives and, worse, a subsequent repair
            # would rewrite history to delete them.
            if (
                migration_type
                and hasattr(migration_type, "name")
                and migration_type.name in ("DELETE", "BASELINE")
            ):
                continue
            if isinstance(migration_type, str) and migration_type.upper() in (
                "DELETE",
                "BASELINE",
            ):
                continue

            # Skip if already marked as deleted (has DELETE entry)
            if script_name in deleted_scripts:
                continue

            # If the script is not in filesystem, add to repairs
            if script_name not in filesystem_scripts:
                repairs.append(
                    {
                        "type": "MISSING_SCRIPT",
                        "script": script_name,
                        "version": getattr(applied, "version", None),
                        "description": getattr(applied, "description", ""),
                        "original_type": getattr(applied, "type", None),  # Preserve original type
                    }
                )

        # Check for failed migrations that need to be cleaned up
        for failed_migration in getattr(migration_state, "failed_objects", []):
            script_name = getattr(failed_migration, "script_name", "")
            if script_name:
                repairs.append(
                    {
                        "type": "FAILED_MIGRATION",
                        "script": script_name,
                        "version": getattr(failed_migration, "version", None),
                        "description": getattr(failed_migration, "description", ""),
                    }
                )

        return repairs

    def _detect_checksum_drift(
        self,
        migration_state: MigrationState,
        existing_repairs: List[Dict[str, Any]],
        scripts_dir: Path,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
    ) -> List[Dict[str, Any]]:
        """Detect checksum drift for applied versioned migrations not already in repairs.

        MigrationState currently only tracks repeatable checksum changes, so this
        performs an explicit comparison against the filesystem for all applied SQL migrations.

        Args:
            migration_state: Current migration state
            existing_repairs: Already-collected repair dicts (to avoid duplicates)
            scripts_dir: Directory containing migration scripts
            recursive: Whether to scan directories recursively
            additional_dirs: Additional directories to scan
            dir_recursive_map: Per-directory recursive override map

        Returns:
            List of additional CHECKSUM_MISMATCH repair dicts
        """
        repairs: List[Dict[str, Any]] = []

        # Additional safeguard: detect checksum drift for applied versioned migrations
        # MigrationState currently only tracks repeatable checksum changes, so perform an explicit comparison
        try:
            filesystem_migrations = self.script_manager.load_migration_scripts(
                scripts_dir,
                recursive=recursive,
                additional_dirs=additional_dirs,
                dir_recursive_map=dir_recursive_map,
            )
            filesystem_lookup: Dict[str, object] = {}
            for migration_group in filesystem_migrations.values():
                for migration_entry in migration_group:
                    filesystem_lookup[migration_entry.script_name] = migration_entry
        except Exception as load_err:
            self.log.warning(f"Unable to load filesystem migrations during repair: {load_err}")
            filesystem_lookup = {}

        already_recorded_scripts = {
            entry["script"] for entry in existing_repairs if "script" in entry
        }

        # Use all_applied_objects (includes undone migrations) for integrity checks.
        # Fall back to applied_objects only if all_applied_objects is missing or not a list —
        # an empty list means "no applied rows in history", not "fetch applied_objects instead".
        all_applied = getattr(migration_state, "all_applied_objects", None)
        if not isinstance(all_applied, list):
            all_applied = getattr(migration_state, "applied_objects", [])
            if not isinstance(all_applied, list):
                all_applied = []
        for applied_migration in all_applied:
            if not is_migration_type(getattr(applied_migration, "type", None), "SQL"):
                continue

            script_name = getattr(applied_migration, "script_name", "")
            if not script_name or script_name in already_recorded_scripts:
                continue

            db_checksum = getattr(applied_migration, "checksum", None)
            fs_migration = filesystem_lookup.get(script_name)
            fs_checksum = getattr(fs_migration, "checksum", None) if fs_migration else None

            if fs_checksum is not None and db_checksum is not None and fs_checksum != db_checksum:
                repairs.append(
                    {
                        "type": "CHECKSUM_MISMATCH",
                        "script": script_name,
                        "old_checksum": db_checksum,
                        "new_checksum": fs_checksum,
                    }
                )
                already_recorded_scripts.add(script_name)

        return repairs

    def _is_failed_migration(self, script: str, migration_state: Any) -> bool:
        """Return True if `script` is in the failed_objects set of `migration_state`."""
        if not script or migration_state is None:
            return False
        failed_objects = getattr(migration_state, "failed_objects", []) or []
        for failed in failed_objects:
            if getattr(failed, "script_name", "") == script:
                return True
        return False

    def _delete_failed_migration_entry(self, repair: Dict[str, Any], result: RepairResult) -> bool:
        """Delete a failed migration row from history so it can be retried.

        Shared by the FAILED_MIGRATION branch and the CHECKSUM_MISMATCH-on-failed-row branch
        of the repair loop. Returns True when a row was actually deleted.
        """
        script_name = repair.get("script", "")
        version = repair.get("version")

        try:
            # BUG-03 (ADR-0015): must use the normalized name — passing the
            # raw lowercase "dblift_schema_history" through
            # ``get_schema_qualified_name`` produces ``"DBLIFT_TEST"."dblift_schema_history"``
            # on Oracle, and Oracle reads that as a literally-named
            # lowercase table → ORA-00942. ``normalized_history_table``
            # returns ``"DBLIFT_SCHEMA_HISTORY"`` for UPPERCASE dialects.
            table_name = self.history_manager.normalized_history_table
            schema = self.config.database.schema
            qualified_table = self.provider.get_schema_qualified_name(schema, table_name)

            self.log.debug(f"Removing failed migration entry: {script_name} (version: {version})")

            # Ensure connection is ready
            ensure_provider_connection(self.provider)

            # Non-transactional providers (e.g. CosmosDB) don't support '?' placeholders and use
            # JS-style booleans (false not FALSE). Database providers (and mocks with query_executor)
            # use '?' params.
            is_non_transactional = (
                isinstance(self.provider, TransactionalProvider)
                and not self.provider.supports_transactions()
            )

            # Story 26-9: false literal comes from plugin Quirks
            # (``boolean_false_literal``). Oracle/SQLServer/SQLite use
            # ``"0"``; CosmosDB uses lowercase ``"false"``; the rest
            # default to ``"FALSE"``.
            from db.provider_registry import ProviderRegistry

            db_type_raw = getattr(getattr(self.config, "database", None), "type", None)
            db_type = (str(db_type_raw) if db_type_raw else "").lower()
            false_literal = ProviderRegistry.get_quirks(db_type).boolean_false_literal

            if is_non_transactional:
                safe_script = script_name.replace("'", "''")
                delete_sql = (
                    f"DELETE FROM {qualified_table} "
                    f"WHERE script = '{safe_script}' AND success = {false_literal}"
                )
                rows_affected = self.provider.execute_statement(delete_sql)
            elif hasattr(self.provider, "query_executor"):
                delete_sql = (
                    f"DELETE FROM {qualified_table} "
                    f"WHERE script = ? AND success = {false_literal}"
                )
                rows_affected = self.provider.query_executor.execute_statement(
                    self.provider.connection, delete_sql, [script_name]  # type: ignore[attr-defined]
                )
            else:
                rows_affected = self.provider.execute_statement(
                    f"DELETE FROM {qualified_table} "
                    f"WHERE script = ? AND success = {false_literal}",
                    params=[script_name],
                )

            row_removed = rows_affected > 0
            if (
                rows_affected < 0
                and not is_non_transactional
                and hasattr(self.provider, "execute_query")
            ):
                # Some DBAPIs report an "unknown" rowcount of -1 for DML
                # (e.g. duckdb_engine), so ``rows_affected > 0`` would wrongly
                # read as "nothing removed". Verify the failed row is gone.
                remaining = self.provider.execute_query(
                    f"SELECT 1 FROM {qualified_table} "
                    f"WHERE script = ? AND success = {false_literal}",
                    [script_name],
                )
                row_removed = not remaining

            if row_removed:
                result.failed_migrations_removed = (
                    getattr(result, "failed_migrations_removed", 0) + 1
                )
                # Warn about non-transactional DDL databases
                if (
                    isinstance(self.provider, TransactionalProvider)
                    and not self.provider.supports_transactional_ddl()
                ):
                    self.log.warning(
                        "Failed migration may have committed DDL objects before failure. "
                        'Retry may fail with "object already exists". Inspect schema state '
                        "before retrying, manually drop objects created before the failure, "
                        "or use `clean --clean-enabled` for a full reset."
                    )
                return True

            self.log.warning(f"No failed migration entry found for: {script_name}")
            return False
        except Exception as delete_err:
            self.log.error(f"Failed to reset failed migration entry {script_name}: {delete_err}")
            raise

    def _execute_repair_loop(
        self,
        repairs_needed: List[Dict[str, Any]],
        result: RepairResult,
        migration_state: Any = None,
    ) -> "tuple[int, bool]":
        """Execute all repairs in a transaction, rolling back on any failure.

        Args:
            repairs_needed: List of repair dicts to execute
            result: RepairResult to update with counters and errors
            migration_state: Current migration state; used to detect when a CHECKSUM_MISMATCH
                repair actually targets a failed row that should be deleted instead of updated.

        Returns:
            Tuple of (repairs_executed: int, had_error: bool)
        """
        # Ensure the provider connection is ready before manipulating history
        try:
            ensure_provider_connection(self.provider)
        except Exception as ensure_err:
            self.log.debug(f"Unable to eagerly ensure connection before repair: {ensure_err}")

        # Perform repairs
        transaction_started = False
        repairs_executed = 0
        if hasattr(self.provider, "begin_transaction"):
            try:
                self.provider.begin_transaction()
                transaction_started = True
            except Exception as begin_err:
                self.log.warning(f"Failed to begin repair transaction: {begin_err}")

        if repairs_needed:
            self.log.info(f"Repairing {len(repairs_needed)} migration history issue(s).")

        for repair in repairs_needed:
            try:
                if repair["type"] == "CHECKSUM_MISMATCH":
                    script = str(repair.get("script", ""))
                    # If the targeted row is a failed migration, updating the checksum would
                    # leave the row in a permanently-failed state that subsequent `migrate`
                    # calls skip. Delete it instead so the migration can be retried cleanly.
                    if self._is_failed_migration(script, migration_state):
                        if self._delete_failed_migration_entry(repair, result):
                            repairs_executed += 1
                            self.log.info(
                                f"Removed failed migration entry: {script} - "
                                "migration can now be retried"
                            )
                        continue

                    new_checksum = repair.get("new_checksum")
                    # Epic 17: checksum column is INT; pass int for CRC32, not str
                    if new_checksum is not None and not isinstance(new_checksum, int):
                        try:
                            new_checksum = int(new_checksum)
                        except (TypeError, ValueError):
                            pass
                    if new_checksum is None:
                        raise ExecutionError(
                            f"CHECKSUM_MISMATCH repair for {repair.get('script', '')} "
                            "requires new_checksum"
                        )
                    updated = self.history_manager.repair_checksum(
                        str(repair.get("script", "")), new_checksum
                    )
                    if not updated:
                        raise ExecutionError(
                            f"No history entry updated for {repair['script']}. "
                            "Repair may require manual intervention."
                        )
                    repairs_executed += 1
                    result.checksums_fixed += 1
                    self.log.info(f"Updated checksum for {repair['script']}")

                elif repair["type"] == "MISSING_SCRIPT":
                    # For missing scripts, create a DELETE entry in the history table
                    # This marks the migration as intentionally deleted
                    script_name = repair.get("script", "")
                    version = repair.get("version")
                    description = repair.get("description", "")
                    original_type_obj = repair.get(
                        "original_type"
                    )  # Get original type from repair dict

                    try:
                        # Convert original type to string for storing in description
                        if original_type_obj:
                            if hasattr(original_type_obj, "name"):
                                original_type_name = original_type_obj.name
                            else:
                                original_type_name = str(original_type_obj).upper()
                        else:
                            # Infer from script name
                            if script_name.startswith("V"):
                                original_type_name = "SQL"
                            elif script_name.startswith("R"):
                                original_type_name = "REPEATABLE"
                            elif script_name.startswith("U"):
                                original_type_name = "UNDO_SQL"
                            else:
                                original_type_name = "SQL"

                        # Create DELETE entry with original type embedded in description
                        delete_reason = description or "Marked as deleted via repair command"
                        # Store original type in description: [DELETE:ORIGINAL_TYPE] description
                        enriched_description = f"[DELETE:{original_type_name}] {delete_reason}"

                        delete_migration = Migration.create_delete_migration(
                            script_name=script_name,
                            version=version,
                            reason=enriched_description,
                        )

                        self.log.debug(
                            f"Creating DELETE entry for missing migration: {script_name} (version: {version})"
                        )

                        # Record the DELETE entry in the history table
                        self.history_manager.record_migration(
                            delete_migration, success=True, execution_time=0
                        )

                        repairs_executed += 1
                        result.deleted_migrations_marked = (
                            getattr(result, "deleted_migrations_marked", 0) + 1
                        )
                        self.log.info(
                            f"Marked migration as deleted: {script_name} - "
                            f"DELETE entry created in history"
                        )
                    except Exception as delete_err:
                        self.log.error(
                            f"Failed to mark migration as deleted {script_name}: {delete_err}"
                        )
                        raise

                elif repair["type"] == "FAILED_MIGRATION":
                    # Remove failed migration entry from history to allow retry
                    # (same approach as Flyway: repair deletes FAILED entries).
                    if self._delete_failed_migration_entry(repair, result):
                        repairs_executed += 1
                        self.log.info(
                            f"Removed failed migration entry: {repair.get('script', '')} - "
                            "migration can now be retried"
                        )
            except Exception as e:
                self.log.error(f"Failed to repair {repair['script']}: {e}")
                result.set_error(f"Repair failed: {e}")
                if hasattr(self.provider, "rollback_transaction") and transaction_started:
                    try:
                        self.provider.rollback_transaction()
                        self.log.debug("Rolled back repair transaction due to failure")
                    except Exception as rollback_err:
                        self.log.warning(f"Failed to rollback repair transaction: {rollback_err}")
                return repairs_executed, True

        if repairs_executed and hasattr(self.provider, "commit_transaction"):
            try:
                self.provider.commit_transaction()
                self.log.debug("Committed repair transaction")
            except Exception as commit_err:
                self.log.error(f"Failed to commit repair transaction: {commit_err}")
                result.set_error(f"Repair operation failed: {commit_err}")
                if hasattr(self.provider, "rollback_transaction") and transaction_started:
                    try:
                        self.provider.rollback_transaction()
                        self.log.debug("Rolled back repair transaction after commit failure")
                    except Exception as rollback_err:
                        self.log.warning(f"Failed to rollback repair transaction: {rollback_err}")
                return repairs_executed, True

        return repairs_executed, False

    def _validate_post_repair_state(
        self,
        migration_state: MigrationState,
        repairs_needed: List[Dict[str, Any]],
        scripts_dir: Path,
        recursive: bool,
        additional_dirs: Optional[List[Path]],
        dir_recursive_map: Optional[Dict[Path, bool]],
        result: RepairResult,
    ) -> bool:
        """Re-compute state after repairs to verify they applied successfully.

        Args:
            migration_state: The pre-repair migration state (unused; kept for symmetry)
            repairs_needed: The repairs that were attempted
            scripts_dir: Directory containing migration scripts
            recursive: Whether to scan directories recursively
            additional_dirs: Additional directories to scan
            dir_recursive_map: Per-directory recursive override map
            result: RepairResult to set error on if validation fails

        Returns:
            True if a validation error was detected (caller should return early), False otherwise
        """
        try:
            post_state = self.state_manager.build_state(
                scripts_dir,
                recursive=recursive,
                additional_dirs=additional_dirs,
                dir_recursive_map=dir_recursive_map,
            )
            repaired_scripts = {repair["script"] for repair in repairs_needed}
            remaining_issues = [
                change.script_name
                for change in getattr(post_state, "checksum_changes", [])
                if change.script_name in repaired_scripts
            ]
            if remaining_issues:
                issue_list = ", ".join(remaining_issues)
                message = (
                    f"Checksum repair incomplete for: {issue_list}. "
                    "Please inspect history table manually."
                )
                self.log.error(message)
                result.set_error(message)
                return True
        except Exception as e:
            self.log.debug(f"Could not rebuild state after repair: {e}")

        return False

    def _build_repair_summary(self, result: RepairResult) -> None:
        """Log a summary of completed repairs.

        Args:
            result: RepairResult containing counters for fixed/reset/marked items
        """
        summary_parts = []
        if result.checksums_fixed > 0:
            summary_parts.append(f"{result.checksums_fixed} checksum(s) fixed")
        if result.failed_migrations_removed > 0:
            summary_parts.append(f"{result.failed_migrations_removed} failed migration(s) reset")
        if result.deleted_migrations_marked > 0:
            summary_parts.append(
                f"{result.deleted_migrations_marked} missing migration(s) marked as deleted"
            )

        if summary_parts:
            self.log.info(f"Repair operation completed successfully: {', '.join(summary_parts)}")
        else:
            self.log.info("Repair operation completed successfully")
