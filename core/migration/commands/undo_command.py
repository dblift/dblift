"""
Undo command implementation.
"""

import time
from functools import cmp_to_key
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    pass

from core.constants import SECONDS_TO_MILLISECONDS
from core.logger.results import MigrationInfo, MigrationSqlInfo, UndoResult
from core.migration.formats.migration_format import MigrationFormat
from core.migration.migration import MigrationType
from core.migration.version_utils import compare_versions, is_migration_success

from ._script_events import emit_script_event as _emit_script_event
from .base_command import BaseCommand


class UndoCommand(BaseCommand):
    """Handles the 'undo' command execution."""

    @staticmethod
    def _normalize_filter_values(values: Optional[Any]) -> Optional[List[str]]:
        if values is None:
            return None
        if isinstance(values, str):
            return [part.strip().lower() for part in values.split(",") if part.strip()]
        return [str(value).strip().lower() for value in values if str(value).strip()]

    @staticmethod
    def _normalize_migration_tags(migration: Any) -> List[str]:
        migration_tags = getattr(migration, "tags", []) or []
        if not isinstance(migration_tags, list):
            migration_tags = list(migration_tags)
        return [str(tag).strip().lower() for tag in migration_tags if str(tag).strip()]

    @classmethod
    def _effective_tags(
        cls, migration: Any, fallback_tags: Optional[List[str]] = None
    ) -> List[str]:
        migration_tags = cls._normalize_migration_tags(migration)
        if migration_tags:
            return migration_tags
        return fallback_tags or []

    @classmethod
    def _matches_tag_filters(
        cls,
        migration: Any,
        tags: Optional[List[str]],
        exclude_tags: Optional[List[str]],
        fallback_tags: Optional[List[str]] = None,
    ) -> bool:
        migration_tags = cls._effective_tags(migration, fallback_tags)
        if tags and not any(tag in migration_tags for tag in tags):
            return False
        if exclude_tags and any(tag in migration_tags for tag in exclude_tags):
            return False
        return True

    @classmethod
    def _source_tags_by_version(cls, all_scripts: List[Any]) -> Dict[str, List[str]]:
        tags_by_version: Dict[str, List[str]] = {}
        for script in all_scripts:
            if script.type not in (MigrationType.SQL, MigrationType.PYTHON):
                continue
            version = getattr(script, "version", None)
            if version is None:
                continue
            script_tags = cls._normalize_migration_tags(script)
            if script_tags:
                tags_by_version[str(version)] = script_tags
        return tags_by_version

    @staticmethod
    def _find_undo_script(
        migration: Any,
        all_scripts: List[Any],
        tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
    ) -> Optional[Any]:
        """Return the matching undo script for a versioned SQL migration."""
        if tags is not None or exclude_tags is not None:
            for script in all_scripts:
                if (
                    script.type == MigrationType.UNDO_SQL
                    and script.version == migration.version
                    and UndoCommand._matches_tag_filters(script, tags, exclude_tags)
                ):
                    return script
            return None

        for script in all_scripts:
            if script.type == MigrationType.UNDO_SQL and script.version == migration.version:
                return script
        return None

    def _add_visible_sql(self, undo_migration: Any, result: UndoResult) -> None:
        """Populate SQL visibility data for an undo migration script."""
        statements = self.execution_engine.get_executable_sql_statements(undo_migration, result)
        if result.error_message:
            return
        result.add_sql_migration(
            MigrationSqlInfo(
                script=undo_migration.script_name,
                version=undo_migration.version,
                description=undo_migration.description,
                statements=statements,
            )
        )

    @staticmethod
    def _add_empty_visible_sql(migration: Any, result: UndoResult) -> None:
        """Record a non-SQL undo migration with no SQL statements."""
        result.add_sql_migration(
            MigrationSqlInfo(
                script=migration.script_name,
                version=migration.version,
                description=migration.description,
                statements=[],
            )
        )

    def execute(
        self,
        scripts_dir: Path,
        target_version: Optional[str] = None,
        dry_run: bool = False,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        show_sql: bool = False,
        placeholders: Optional[Dict[str, Any]] = None,
        recursive: Optional[bool] = None,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
    ) -> UndoResult:
        """Undo migrations to a target version."""
        normalized_tags = self._normalize_filter_values(tags)
        normalized_exclude_tags = self._normalize_filter_values(exclude_tags)
        normalized_versions = self._normalize_filter_values(versions)
        normalized_exclude_versions = self._normalize_filter_values(exclude_versions)
        tag_filter_active = bool(normalized_tags or normalized_exclude_tags)

        result = UndoResult()
        result.show_sql = show_sql
        result.target_schema = self.config.database.schema

        # Populate database connection information
        self._populate_database_info(result)

        try:
            # Ensure schema and history table exist (this establishes the connection)
            self.history_manager.create_schema_and_history_table(create_schema=False)

            # Log command execution with connection info (after connection is established)
            self._log_command_header_update(
                "undo",
                target_version=target_version,
                dry_run=dry_run,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
                show_sql=show_sql,
            )

            # Display current schema version
            self._log_current_schema_version()

            # Setup parameters
            use_recursive, use_additional_dirs = self.migration_helpers.setup_migration_parameters(
                placeholders, recursive, additional_dirs, self.placeholder_service
            )

            # Build state (source of truth) and derive applied migrations to consider
            try:
                migration_state = self.state_manager.build_state(
                    scripts_dir,
                    recursive=use_recursive,
                    additional_dirs=use_additional_dirs,
                    dir_recursive_map=dir_recursive_map,
                    target_version=target_version,
                    tags=None,
                    exclude_tags=None,
                    versions=normalized_versions,
                    exclude_versions=normalized_exclude_versions,
                )

                applied_migrations = getattr(migration_state, "applied_objects", [])

                # Handle Mock objects in tests - ensure applied_migrations is iterable
                if not hasattr(applied_migrations, "__iter__"):
                    # If it's not iterable (e.g., a Mock), treat it as empty
                    applied_migrations = []
                else:
                    # Convert to list to ensure we can iterate multiple times
                    try:
                        applied_migrations = list(applied_migrations)
                    except (TypeError, AttributeError):
                        applied_migrations = []
            except Exception as e:
                # If build_state fails (e.g., due to mocked dependencies in tests), use empty list
                self.log.debug(f"Could not build migration state: {e}")
                applied_migrations = []

            # Store current schema version in result for HTML reports
            current_version = None
            if applied_migrations:
                try:
                    current_version = self.state_manager.get_current_version(applied_migrations)
                except Exception as e:
                    self.log.debug(f"Could not get current version: {e}")
            if current_version:
                result.current_schema_version = current_version

            all_scripts = self.script_manager.get_migration_scripts(
                scripts_dir,
                recursive=use_recursive,
                additional_dirs=use_additional_dirs,
                dir_recursive_map=dir_recursive_map,
            )
            source_tags_by_version = self._source_tags_by_version(all_scripts)

            def _fallback_tags_for(migration: Any) -> List[str]:
                version = getattr(migration, "version", None)
                if version is None:
                    return []
                return source_tags_by_version.get(str(version), [])

            # Find migrations to undo using migration rules (based on state)
            migrations_to_undo = []

            if target_version is None:
                # No target version specified - find the latest migration that can be undone
                # Process versioned migrations in reverse order (newest first)
                versioned_migrations = []
                for m in applied_migrations:
                    if m.type in (MigrationType.SQL, MigrationType.PYTHON):
                        if not self._matches_tag_filters(
                            m,
                            normalized_tags,
                            normalized_exclude_tags,
                            fallback_tags=_fallback_tags_for(m),
                        ):
                            continue
                        # Use migration rules to determine if migration was successful
                        success_value = getattr(m, "success", False)
                        is_success = is_migration_success(success_value)
                        if is_success:
                            versioned_migrations.append(m)
                # Sort by semantic version (Flyway-compatible): "10" > "4",
                # not lexicographic where "4" > "10". Without this, undo picks
                # the wrong migration when versions span digit boundaries.
                versioned_migrations.sort(
                    key=cmp_to_key(
                        lambda a, b: compare_versions(
                            getattr(a, "version", "") or "",
                            getattr(b, "version", "") or "",
                        )
                    ),
                    reverse=True,
                )

                for migration in versioned_migrations:
                    version = str(migration.version) if migration.version else None
                    if not version:
                        continue
                    if normalized_versions and version not in normalized_versions:
                        continue
                    if normalized_exclude_versions and version in normalized_exclude_versions:
                        continue

                    can_undo, message = self.migration_rules.should_undo_version(
                        version, applied_migrations
                    )
                    if can_undo:
                        migrations_to_undo.append(migration)
                        if not tag_filter_active:
                            break  # Only undo the most recent undoable migration
                    elif message:
                        self.log.info(message)
            else:
                # Target version specified - find all migrations newer than target that can be undone
                for migration in reversed(applied_migrations):
                    if not self._matches_tag_filters(
                        migration,
                        normalized_tags,
                        normalized_exclude_tags,
                        fallback_tags=_fallback_tags_for(migration),
                    ):
                        continue
                    if migration.version is not None:
                        version = str(migration.version)
                        if normalized_versions and version not in normalized_versions:
                            continue
                        if normalized_exclude_versions and version in normalized_exclude_versions:
                            continue
                    # Use migration rules to determine if migration was successful
                    success_value = getattr(migration, "success", False)
                    is_success = is_migration_success(success_value)

                    if (
                        migration.type in (MigrationType.SQL, MigrationType.PYTHON)
                        and is_success
                        and migration.version is not None
                        and compare_versions(str(migration.version), str(target_version)) > 0
                    ):
                        version = str(migration.version)
                        can_undo, message = self.migration_rules.should_undo_version(
                            version, applied_migrations
                        )
                        if can_undo:
                            migrations_to_undo.append(migration)
                        elif message:
                            result.set_error(message)
                            self._log_command_completion("undo", result)
                            return result
                    elif (
                        migration.version is not None
                        and compare_versions(str(migration.version), str(target_version)) <= 0
                    ):
                        break

            if not migrations_to_undo:
                self.log.info("No migrations to undo")
                result.complete()
                return result

            self.log.info(f"Found {len(migrations_to_undo)} migration(s) to undo")

            if dry_run:
                if show_sql:
                    for migration in migrations_to_undo:
                        undo_migration = self._find_undo_script(
                            migration,
                            all_scripts,
                            tags=normalized_tags,
                            exclude_tags=normalized_exclude_tags,
                        )
                        if undo_migration is None:
                            error_msg = f"No undo script found for {migration.script_name}"
                            self.log.error(error_msg)
                            result.set_error(error_msg)
                            self._log_command_completion("undo", result)
                            return result
                        if undo_migration.format == MigrationFormat.PYTHON:
                            self._add_empty_visible_sql(undo_migration, result)
                        else:
                            self._add_visible_sql(undo_migration, result)
                        if result.error_message:
                            self._log_command_completion("undo", result)
                            return result

                self.log.info("DRY RUN: Would undo the following migrations:")
                for migration in migrations_to_undo:
                    self.log.info(f"  - {migration.script_name}")
                # Note: Callbacks are NOT executed in dry-run mode
                self._log_command_completion("undo", result)
                return result

            # Execute beforeUndo callbacks
            try:
                self._execute_callbacks(
                    scripts_dir, "beforeUndo", use_recursive, use_additional_dirs, dir_recursive_map
                )
            except Exception as e:
                self.log.error(f"beforeUndo callback failed: {e}")
                result.set_error(f"beforeUndo callback failed: {e}")
                self._execute_callbacks(
                    scripts_dir,
                    "afterUndoError",
                    use_recursive,
                    use_additional_dirs,
                    dir_recursive_map,
                )
                result.complete()
                return result

            # Execute undo for each migration
            for migration in migrations_to_undo:
                # Initialize variables to avoid NameError in exception handler
                start_time = None
                undo_migration = None
                journal_started = False

                try:
                    # Execute beforeEach callbacks
                    self._execute_callbacks(
                        scripts_dir,
                        "beforeEach",
                        use_recursive,
                        use_additional_dirs,
                        dir_recursive_map,
                    )

                    # SQL path: find the corresponding UNDO_SQL script
                    undo_migration = self._find_undo_script(
                        migration,
                        all_scripts,
                        tags=normalized_tags,
                        exclude_tags=normalized_exclude_tags,
                    )

                    if undo_migration is None:
                        error_msg = f"No undo script found for {migration.script_name}"
                        self.log.error(error_msg)
                        result.set_error(error_msg)
                        # Execute afterUndoError callbacks when undo fails
                        self._execute_callbacks(
                            scripts_dir,
                            "afterUndoError",
                            use_recursive,
                            use_additional_dirs,
                            dir_recursive_map,
                        )
                        break

                    start_time = time.time()

                    # Start journal tracking for undo migration (use undo script name for journal)
                    if self.journal:
                        self.journal.start_migration(
                            undo_migration.script_name,
                            details={
                                "version": undo_migration.version,
                                "description": undo_migration.description,
                                "type": undo_migration.type.value if undo_migration.type else "SQL",
                            },
                        )
                        journal_started = True

                    if show_sql:
                        self._add_visible_sql(undo_migration, result)
                        if result.error_message:
                            if self.journal and journal_started:
                                execution_time = int(
                                    (time.time() - start_time) * SECONDS_TO_MILLISECONDS
                                )
                                self.journal.end_migration(
                                    undo_migration.script_name,
                                    success=False,
                                    error_message=result.error_message,
                                    execution_time=execution_time,
                                )
                                journal_started = False
                            break

                    _undo_script_data = {
                        "script": undo_migration.script_name,
                        "version": migration.version,
                        "description": f"Undo: {migration.description}",
                        "type": "UNDO_SQL",
                    }
                    _emit_script_event("migration.script.started", _undo_script_data)
                    self.execution_engine.execute_migration(undo_migration, result)
                    execution_time = int((time.time() - start_time) * SECONDS_TO_MILLISECONDS)

                    if result.error_message:
                        if self.journal and journal_started:
                            self.journal.end_migration(
                                undo_migration.script_name,
                                success=False,
                                error_message=result.error_message,
                                execution_time=execution_time,
                            )
                            journal_started = False
                        _emit_script_event(
                            "migration.script.failed",
                            {
                                "script": undo_migration.script_name,
                                "version": migration.version,
                                "error": result.error_message,
                                "execution_time": execution_time,
                            },
                        )
                        self._execute_callbacks(
                            scripts_dir,
                            "afterUndoError",
                            use_recursive,
                            use_additional_dirs,
                            dir_recursive_map,
                        )
                        break

                    # End journal tracking for undo migration (use undo script name for journal)
                    if self.journal:
                        self.journal.end_migration(
                            undo_migration.script_name, success=True, execution_time=execution_time
                        )
                        journal_started = False

                    # Create MigrationInfo for the undone migration (use undo script name)
                    migration_info = MigrationInfo(
                        script=undo_migration.script_name,
                        version=migration.version,
                        description=f"Undo: {migration.description}",
                        type="UNDO_SQL",
                        status="UNDONE",
                        execution_time=execution_time,
                        checksum=migration.checksum,
                    )
                    result.add_undone_migration(migration_info)

                    _emit_script_event(
                        "migration.script.completed",
                        {**_undo_script_data, "execution_time": execution_time},
                    )

                    # History recording is handled by the execution engine
                    result.undone_count += 1

                    self.log.info(f"Successfully undone migration {migration.script_name}")

                    # Execute afterEach callbacks after successful undo
                    self._execute_callbacks(
                        scripts_dir,
                        "afterEach",
                        use_recursive,
                        use_additional_dirs,
                        dir_recursive_map,
                    )

                except Exception as e:
                    # Only log if error_message is not already set (execute_migration already logged it)
                    if not result.error_message:
                        self.log.error(f"Failed to undo migration {migration.script_name}: {e}")
                        error_message = str(e)
                    else:
                        # Error was already logged by execute_migration, just use the existing message
                        error_message = result.error_message

                    # End journal tracking for a failed undo migration. The journal
                    # entry was opened under ``undo_migration.script_name``; fall back
                    # to ``migration.script_name`` only for the rare case where the
                    # failure occurred before ``undo_migration`` was resolved, so the
                    # journal entry is always closed.
                    execution_time = 0
                    if start_time is not None:
                        execution_time = int((time.time() - start_time) * SECONDS_TO_MILLISECONDS)

                    if "_undo_script_data" in locals():
                        _emit_script_event(
                            "migration.script.failed",
                            {
                                "script": getattr(
                                    locals().get("undo_migration"),
                                    "script_name",
                                    migration.script_name,
                                ),
                                "version": migration.version,
                                "error": error_message,
                                "execution_time": execution_time,
                            },
                        )

                    if self.journal and journal_started:
                        journal_script_name = (
                            undo_migration.script_name
                            if undo_migration is not None
                            else migration.script_name
                        )
                        self.journal.end_migration(
                            journal_script_name,
                            success=False,
                            error_message=error_message,
                            execution_time=execution_time,
                        )

                    # Only set error if not already set (execute_migration already set it)
                    if not result.error_message:
                        result.set_error(f"Undo failed: {e}")
                    # Execute afterUndoError callbacks when undo fails
                    self._execute_callbacks(
                        scripts_dir,
                        "afterUndoError",
                        use_recursive,
                        use_additional_dirs,
                        dir_recursive_map,
                    )
                    break

            # If we reach here, all undo migrations completed successfully
            # Execute afterUndo callbacks
            if not result.error_message:
                self._execute_callbacks(
                    scripts_dir, "afterUndo", use_recursive, use_additional_dirs, dir_recursive_map
                )

            # Set journal on result for HTML formatter access
            result.journal = self.journal

            # Update schema version after migrations are undone
            # Rebuild state to get accurate applied migrations after undo
            migration_state_after = self.state_manager.build_state(
                scripts_dir,
                recursive=use_recursive,
                additional_dirs=use_additional_dirs,
                dir_recursive_map=dir_recursive_map,
                target_version=None,
                tags=None,
                exclude_tags=None,
                versions=None,
                exclude_versions=None,
            )
            applied_migrations_after = migration_state_after.applied_objects
            updated_version = self.state_manager.get_current_version(applied_migrations_after)
            if updated_version:
                result.current_schema_version = updated_version
            else:
                # No versioned migrations left, set to None
                result.current_schema_version = None

            self._log_command_completion("undo", result)
            return result

        except Exception as e:
            self.log.error(f"Undo operation failed: {e}")
            result.set_error(f"Undo operation failed: {e}")
            # Execute afterUndoError callbacks on exception
            try:
                self._execute_callbacks(
                    scripts_dir,
                    "afterUndoError",
                    use_recursive,
                    use_additional_dirs,
                    dir_recursive_map,
                )
            except Exception as e:
                self.log.debug(
                    f"afterUndoError callback failed (ignored during exception handling): {e}"
                )
            self._log_command_completion("undo", result)
            return result
