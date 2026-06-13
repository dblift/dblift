"""
Main migration executor orchestrator.

This is the primary entry point for all migration operations, now refactored
to use specialized components for better separation of concerns.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from core.migration.commands.base_command import BaseCommandContext

from config import DbliftConfig
from core.logger import Log, NullLog
from core.logger.results import (
    BaselineResult,
    CleanResult,
    InfoResult,
    MigrateResult,
    OperationResult,
    RepairResult,
    UndoResult,
    ValidateResult,
)
from core.migration.history.migration_history_manager import MigrationHistoryManager
from core.migration.journals.migration_journal import MigrationJournal
from core.migration.rules.migration_rules import MigrationRules
from core.migration.scripting.migration_script_manager import MigrationScriptManager
from core.migration.snapshots.schema_snapshot_service import SchemaSnapshotService
from core.migration.sql.sql_analyzer import SqlAnalyzer
from core.migration.state.migration_state_manager import MigrationStateManager
from core.migration.ui.migration_ui import MigrationUI
from core.sql_validator.migration_validator import MigrationValidator
from db.base_provider import BaseProvider

from .execution_engine import ExecutionEngine
from .migration_helpers import MigrationHelpers
from .placeholder_manager import PlaceholderManager


class MigrationExecutor:
    """Main executor class that orchestrates the migration process.

    This class manages database migrations with proper dependency injection,
    enabling efficient connection reuse and consistent state management
    across multiple database operations.
    """

    def __init__(self, provider: "BaseProvider", config: DbliftConfig, log: Log):
        """Initialize the executor with injected provider.

        Args:
            provider: Database provider instance (REQUIRED - injected via dependency injection)
            config: Application configuration
            log: Logger for logging events
        """
        if provider is None:
            raise ValueError("provider is required (must be injected via dependency injection)")
        if config is None or log is None:
            raise ValueError("config and log are required")

        # Store injected provider
        self.provider = provider
        self.config = config
        self.log = log if log is not None else NullLog()

        # Initialize specialized components
        self.placeholder_manager = PlaceholderManager(config, log)
        self.placeholder_manager.executor = self  # Set executor reference for get_installed_by
        self.migration_helpers = MigrationHelpers(config, log)

        # Initialize placeholders early so they're available for validator
        self.placeholders = self.placeholder_manager.init_placeholders()

        # Initialize PlaceholderService
        from core.migration.placeholders.placeholder_service import (
            PlaceholderService,
        )

        self.placeholder_service = PlaceholderService(self.placeholders, log)
        self.placeholder_manager.placeholder_service = self.placeholder_service

        # Debug: Track schema usage at executor instantiation
        schema = getattr(config.database, "schema", None)
        self.log.debug(f"[DEBUG] MigrationExecutor __init__: config.database.schema={schema}")

        # Get custom history table name if provided
        custom_table = getattr(config, "history_table", None)
        self.log.debug(f"[DEBUG] MigrationExecutor: custom_table from config = {custom_table}")

        # Create core components
        logger = log
        script_encoding = getattr(config.migrations, "script_encoding", "utf-8")
        detect_encoding = getattr(config.migrations, "detect_encoding", False)
        self.script_manager = MigrationScriptManager(logger, script_encoding, detect_encoding)
        self.history_manager = MigrationHistoryManager(
            provider=self.provider,
            schema=config.database.schema,
            installed_by=self.get_installed_by(),
            logger=log,
            table_name=custom_table,
        )
        self.log.debug(
            f"[DEBUG] MigrationExecutor: history_manager.history_table = {self.history_manager.history_table}"
        )

        # Link components together
        self.history_manager.script_manager = self.script_manager
        self.validator = MigrationValidator(
            self.script_manager, self.history_manager, log, self.placeholders
        )
        self.ui = MigrationUI(log)
        self.migration_ui = self.ui  # Alias for backward compatibility/consistency
        self.rules = MigrationRules(log)

        # Initialize SQL analyzer and execution engine
        self.sql_analyzer = SqlAnalyzer(dialect=config.database.type)
        self.journal = MigrationJournal(enabled=config.journal_enabled)

        # Initialize SqlExecutionService for journal support
        from ..sql.sql_execution_service import SqlExecutionService

        self.sql_execution_service = SqlExecutionService(
            provider=self.provider,
            sql_analyzer=self.sql_analyzer,
            logger=log,
            journal=self.journal,
            schema=config.database.schema,
        )

        # Pass SqlExecutionService and history manager to ExecutionEngine for journal tracking and transaction management
        self.execution_engine = ExecutionEngine(
            self.provider,
            self.sql_analyzer,
            log,
            self.sql_execution_service,
            self.history_manager,
            self.placeholder_service,
            config=self.config,
        )

        # Initialize snapshot service for canonical schema tracking
        self.snapshot_service = SchemaSnapshotService(
            config=self.config,
            provider=self.provider,
            history_manager=self.history_manager,
            log=self.log,
        )

        # Initialize MigrationStateManager for centralized state management
        self.state_manager = MigrationStateManager(
            log,
            history_manager=self.history_manager,
            script_manager=self.script_manager,
            migration_rules=self.rules,
        )

    def _make_command_context(self) -> "BaseCommandContext":
        """Build a :class:`~core.migration.commands.base_command.BaseCommandContext`
        from this executor's shared infrastructure components.

        All eight migration commands receive the same 13 infrastructure dependencies
        from the executor.  Building the context object once here removes the
        repetition at each instantiation site.

        Returns:
            BaseCommandContext populated from this executor's components.
        """
        from core.migration.commands.base_command import BaseCommandContext

        return BaseCommandContext(
            config=self.config,
            log=self.log,
            provider=self.provider,
            script_manager=self.script_manager,
            history_manager=self.history_manager,
            validator=self.validator,
            execution_engine=self.execution_engine,
            migration_helpers=self.migration_helpers,
            state_manager=self.state_manager,
            migration_ui=self.migration_ui,
            migration_rules=self.rules,
            journal=self.journal,
            placeholder_service=self.placeholder_service,
        )

    def get_installed_by(self) -> str:
        """Get the username to use for recording migrations.

        Priority order:
        1. DbliftConfig.installed_by
        2. DatabaseConfig.installed_by
        3. DatabaseConfig.username

        Returns:
            The username to use for recording migrations
        """
        if hasattr(self.config, "installed_by") and self.config.installed_by:
            return self.config.installed_by
        elif hasattr(self.config.database, "installed_by") and self.config.database.installed_by:
            return self.config.database.installed_by
        else:
            return self.config.database.username

    def migrate(
        self,
        scripts_dir: Path,
        dry_run: bool = False,
        target_version: Optional[str] = None,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        mark_as_executed: bool = False,
        show_sql: bool = False,
        placeholders: Optional[Dict[str, Any]] = None,
        recursive: Optional[bool] = None,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
    ) -> MigrateResult:
        """Execute database migrations using the dedicated MigrateCommand class."""
        from core.migration.commands.migrate_command import MigrateCommand

        command = MigrateCommand(
            self._make_command_context(),
            snapshot_service=self.snapshot_service,
        )

        result = command.execute(
            scripts_dir=scripts_dir,
            dry_run=dry_run,
            target_version=target_version,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
            mark_as_executed=mark_as_executed,
            show_sql=show_sql,
            placeholders=placeholders,
            recursive=recursive,
            additional_dirs=additional_dirs,
            dir_recursive_map=dir_recursive_map,
        )

        has_applied_migrations = False
        if hasattr(result, "migrations_applied"):
            migrations_applied = result.migrations_applied
            try:
                has_applied_migrations = bool(list(migrations_applied))
            except TypeError:
                has_applied_migrations = bool(migrations_applied)
        elif hasattr(result, "migrations"):
            has_applied_migrations = bool(result.migrations)

        if not dry_run and getattr(result, "success", False) and has_applied_migrations:
            self._capture_snapshot("migrate", result)
        return result

    def undo(
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
        """Undo migrations using the dedicated UndoCommand class."""
        from core.migration.commands.undo_command import UndoCommand

        command = UndoCommand(self._make_command_context())

        result = command.execute(
            scripts_dir=scripts_dir,
            target_version=target_version,
            dry_run=dry_run,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
            show_sql=show_sql,
            placeholders=placeholders,
            recursive=recursive,
            additional_dirs=additional_dirs,
            dir_recursive_map=dir_recursive_map,
        )
        if not dry_run and getattr(result, "success", False):
            self._capture_snapshot("undo", result)
        return result

    def clean(
        self,
        scripts_dir: Optional[Path] = None,
        dry_run: bool = False,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
        **kwargs: Any,
    ) -> CleanResult:
        """Clean database using the dedicated CleanCommand class."""
        from core.migration.commands.clean_command import CleanCommand

        command = CleanCommand(self._make_command_context())

        # Explicit clean() parameters win over duplicate keys in kwargs (e.g. client forwards **kwargs).
        _clean_explicit_keys = frozenset(
            {
                "dry_run",
                "scripts_dir",
                "recursive",
                "additional_dirs",
                "dir_recursive_map",
            }
        )
        execute_extras = {k: v for k, v in kwargs.items() if k not in _clean_explicit_keys}

        result = command.execute(
            dry_run=dry_run,
            scripts_dir=scripts_dir,
            recursive=recursive,
            additional_dirs=additional_dirs,
            dir_recursive_map=dir_recursive_map,
            **execute_extras,
        )
        return result

    def validate(
        self,
        scripts_dir: Path,
        skip_validation: bool = False,
        target_version: Optional[str] = None,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
    ) -> ValidateResult:
        """Validate migrations using the dedicated ValidateCommand class."""
        from core.migration.commands.validate_command import ValidateCommand

        command = ValidateCommand(self._make_command_context())

        return command.execute(
            scripts_dir=scripts_dir,
            recursive=recursive,
            additional_dirs=additional_dirs,
            dir_recursive_map=dir_recursive_map,
            target_version=target_version,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
        )

    def info(
        self,
        scripts_dir: Path,
        target_version: Optional[str] = None,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
        display_human: bool = True,
    ) -> InfoResult:
        """Get migration info using the dedicated InfoCommand class."""
        from core.migration.commands.info_command import InfoCommand

        command = InfoCommand(self._make_command_context())

        return command.execute(
            scripts_dir=scripts_dir,
            recursive=recursive,
            additional_dirs=additional_dirs,
            dir_recursive_map=dir_recursive_map,
            display_human=display_human,
        )

    def baseline(
        self, baseline_version: str, baseline_description: str = "", dry_run: bool = False
    ) -> BaselineResult:
        """Create baseline using the dedicated BaselineCommand class."""
        from core.migration.commands.baseline_command import BaselineCommand

        command = BaselineCommand(self._make_command_context())

        result = command.execute(
            baseline_version=baseline_version,
            baseline_description=baseline_description,
            dry_run=dry_run,
        )
        if getattr(result, "success", False) and not dry_run:
            self._capture_snapshot("baseline", result)
        return result

    def repair(
        self,
        scripts_dir: Path,
        dry_run: bool = False,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
    ) -> RepairResult:
        """Repair migrations using the dedicated RepairCommand class."""
        from core.migration.commands.repair_command import RepairCommand

        command = RepairCommand(self._make_command_context())

        return command.execute(
            scripts_dir=scripts_dir,
            dry_run=dry_run,
            recursive=recursive,
            additional_dirs=additional_dirs,
            dir_recursive_map=dir_recursive_map,
        )

    def import_flyway(
        self,
        scripts_dir: Path,
        dry_run: bool = False,
        flyway_table: str = "flyway_schema_history",
    ) -> OperationResult:
        """Import Flyway history using the import flyway command."""
        from core.migration.commands.import_flyway_command import ImportFlywayCommand

        command = ImportFlywayCommand(self._make_command_context())

        return command.execute(
            scripts_dir=scripts_dir,
            dry_run=dry_run,
            flyway_table=flyway_table,
        )

    def _capture_snapshot(
        self,
        operation: str,
        result: Optional[OperationResult] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Capture a snapshot of the current schema state."""
        if not getattr(self, "snapshot_service", None):
            return
        if result is not None and not getattr(result, "success", False):
            return
        # Skip snapshot capture when the provider explicitly declares it is not
        # supported. Defaults to True for all providers. Override
        # supports_snapshots() → False for any provider where the snapshot
        # repository's parameterized queries cannot be executed.
        supports_snap = getattr(self.provider, "supports_snapshots", None)
        if callable(supports_snap) and not supports_snap():
            return

        metadata: Dict[str, Any] = {"operation": {"name": operation}}
        if extra_metadata:
            metadata.update(extra_metadata)

        op_meta = metadata.setdefault("operation", {})
        if result is not None:
            if hasattr(result, "current_schema_version") and result.current_schema_version:
                op_meta["current_schema_version"] = result.current_schema_version
            if hasattr(result, "migrations_applied"):
                op_meta["migrations_applied"] = result.migrations_applied

        try:
            self.snapshot_service.capture_snapshot(operation, extra_metadata=metadata)
        except Exception as exc:
            warning = (
                f"Failed to capture schema snapshot after {operation}: {exc}. "
                "Commands using --source=database-stored will not see this operation's snapshot; "
                "use --source=live-database to capture the current schema."
            )
            self.log.warning(warning)
            add_warning = getattr(result, "add_warning", None) if result is not None else None
            if callable(add_warning):
                add_warning(warning)

    def cleanup(self) -> None:
        """Clean up resources when the executor is no longer needed."""
        # Call cleanup() on all major components if available
        for attr in ["provider", "history_manager", "script_manager", "validator", "ui"]:
            obj = getattr(self, attr, None)
            if obj and hasattr(obj, "cleanup"):
                try:
                    obj.cleanup()
                    self.log.debug(f"Cleaned up {attr}")
                except Exception as e:
                    self.log.warning(f"Error cleaning up {attr}: {e}")

        # Clean up connection pool if it exists
        try:
            if hasattr(self.provider, "close_all_connections"):
                self.provider.close_all_connections()
                self.log.debug("Closed all database connections")
        except Exception as e:
            self.log.warning(f"Error closing database connections: {e}")

        self.log.debug("MigrationExecutor cleanup completed")
