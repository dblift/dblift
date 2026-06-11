"""Operation result containers returned by the command layer.

Each ``*Result`` class subclasses :class:`OperationResult` and carries the
typed payload (migrations applied, objects dropped, snapshots, ...) that
formatters and the JSON/HTML report writers consume.
"""

from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Union

if TYPE_CHECKING:
    from core.migration.migration_journal import MigrationJournal


# Base class for all operation results
class OperationResult:
    """Base class for operation results."""

    def __init__(
        self,
        success: bool = True,
        error_message: Optional[str] = None,
        error: Optional[str] = None,
        data: Any = None,
    ) -> None:
        """Initialize the common result envelope: success flag, error, timing, and metadata."""
        self.success: bool = success
        # Support both error and error_message for backward compatibility
        self.error_message: Optional[str] = error if error is not None else error_message
        self.warnings: List[str] = []
        self.start_time: datetime = datetime.now()
        self.end_time: Optional[datetime] = None
        self.data: Any = data
        self.message: Optional[str] = None  # Informational message for successful operations
        self.journal: Optional["MigrationJournal"] = None  # Will hold the MigrationJournal object
        self.target_schema: str = ""  # Schema target for the operation
        self.cli_options: dict[str, Any] = {}  # Store CLI options used for the command
        self.show_sql: bool = False
        self.sql: List["MigrationSqlInfo"] = []
        # None when not applicable; True/False when a failed migration row was/was not
        # persisted to history after an execution failure.
        self.failed_history_persisted: Optional[bool] = None

        # Database connection information for reports
        self.db_version: Optional[str] = None  # Database version (e.g., "PostgreSQL 15.14")
        self.native_driver: Optional[str] = None  # Native driver info
        self.database_url_masked: Optional[str] = None  # Masked database URL for security
        self.server_name: Optional[str] = None  # Database server name/IP

        # Batch-5 BUG-06: ``schema_name`` and ``target_schema`` represent the
        # same concept but were populated inconsistently — commands set
        # ``target_schema`` while the text formatter reads ``schema_name``,
        # so API callers observed an empty ``InfoResult.schema_name``.
        # Promote ``schema_name`` to a property that falls back to
        # ``target_schema`` while still accepting an explicit override
        # (CleanResult.add_cleaned_object writes it from dropped-object
        # metadata).
        self._schema_name: Optional[str] = None

    @property
    def schema_name(self) -> str:
        """Return the explicit schema name if set, else ``target_schema``."""
        if self._schema_name is not None:
            return self._schema_name
        return self.target_schema

    @schema_name.setter
    def schema_name(self, value: Optional[str]) -> None:
        """Override the schema name (used by clean to record per-object schema)."""
        self._schema_name = value

    def add_warning(self, warning: str) -> None:
        """Add a warning to the result."""
        self.warnings.append(warning)

    def add_sql_migration(self, migration_sql: "MigrationSqlInfo") -> None:
        """Add SQL visibility data for one migration script."""
        self.sql.append(migration_sql)

    def set_error(self, error_message: str) -> None:
        """Set an error message and mark the operation as failed."""
        self.error_message = error_message
        self.success = False

    def complete(self) -> None:
        """Mark the operation as complete."""
        self.end_time = datetime.now()

    def execution_time(self) -> int:
        """Get the total execution time in milliseconds."""
        if self.end_time is None:
            return 0
        delta = self.end_time - self.start_time
        return int(delta.total_seconds() * 1000)


# Model for migration information
class MigrationInfo:
    """Contains information about a migration."""

    def __init__(
        self,
        script: str,
        version: Optional[Union[str, int]] = None,
        description: str = "",
        type: str = "SQL",
        status: str = "PENDING",
        installed_on: Optional[datetime] = None,
        installed_by: Optional[str] = None,
        checksum: Optional[int] = None,
        execution_time: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """Store the per-migration descriptor (script, version, status, timing, error)."""
        self.script = script
        self.version = version
        self.description = description
        self.type = type
        self.status = status
        self.installed_on = installed_on
        self.installed_by = installed_by
        self.checksum = checksum
        self.execution_time = execution_time  # milliseconds
        self.error = error

    def __str__(self) -> str:
        return (
            f"{self.script} [{self.version}] - {self.description} " f"[{self.type}] - {self.status}"
        )


class MigrationSqlInfo:
    """SQL statements visible for a migration when ``--show-sql`` is enabled."""

    def __init__(
        self,
        script: str,
        version: Optional[Union[str, int]] = None,
        description: str = "",
        statements: Optional[List[str]] = None,
    ) -> None:
        """Store per-migration SQL statements after parser/execution filtering."""
        self.script = script
        self.version = version
        self.description = description
        self.statements = statements or []


# Result classes for different operations
class CommandResult(OperationResult):
    """Result of a command operation."""

    def __init__(self) -> None:
        """Initialize an empty command result (command type + captured output lines)."""
        super().__init__()
        self.command_type: str = ""
        self.output: List[str] = []

    def add_output(self, output: str) -> None:
        """Add output to the result."""
        self.output.append(output)

    def get_output(self) -> List[str]:
        """Get the command output."""
        return self.output


class MigrateResult(OperationResult):
    """Result of a migrate operation."""

    def __init__(self) -> None:
        """Initialize empty migration list and the schema/version/dry-run bookkeeping."""
        super().__init__()
        self.migrations: List[MigrationInfo] = []
        self.target_schema: str = ""
        self.init_schema: bool = False
        self.init_version: Optional[str] = None
        self.success = True
        self.current_schema_version: Optional[str] = None
        self.dry_run_count: int = 0

    def add_migration(self, migration: MigrationInfo) -> None:
        """Add a migration to the result."""
        self.migrations.append(migration)
        # If any migration has a failed status, mark the result as failed
        # Handle both "SUCCESS" and "Success" for backward compatibility
        if migration.status not in ["SUCCESS", "Success"]:
            self.success = False

    def is_successful(self) -> bool:
        """Check if the migration was successful."""
        if not self.migrations:
            return self.success
        # Handle both "SUCCESS" and "Success" for backward compatibility
        return self.success and all(m.status in ["SUCCESS", "Success"] for m in self.migrations)

    @property
    def error(self) -> Optional[str]:
        """Get the error message for the migration operation."""
        return self.error_message

    @property
    def migrations_applied(self) -> List[str]:
        """Get a list of version strings or script names for successfully applied migrations."""
        applied = []
        for migration in self.migrations:
            # Handle both "SUCCESS" and "Success" for backward compatibility
            if migration.status in ["SUCCESS", "Success"]:
                # For versioned migrations, return the version
                if migration.version:
                    applied.append(str(migration.version))
                # For repeatable migrations, return the script name
                else:
                    applied.append(migration.script)
        return applied

    def set_error(self, error_message: str) -> None:
        """Set an error message and mark the operation as failed."""
        self.success = False
        # Fix typo in error messages
        if error_message and isinstance(error_message, str):
            error_message = error_message.replace("\nVersion", "Version").replace(
                "nversion", "version"
            )
        super().set_error(error_message)


class CleanResult(OperationResult):
    """Result of a clean operation."""

    def __init__(self) -> None:
        """Initialize empty per-type object buckets and detail metadata."""
        super().__init__()
        self.target_schema: str = ""
        # ``schema_name`` comes from OperationResult as a property (BUG-06).
        self._objects_by_type: Dict[str, Set[str]] = defaultdict(set)
        self._object_details: Dict[str, Dict[str, Dict[str, str]]] = defaultdict(dict)

    def add_cleaned_object(
        self,
        object_type: str,
        name: str,
        schema: Optional[str] = None,
        details: Optional[Dict[str, str]] = None,
    ) -> None:
        """Record an object that was removed during clean."""
        if not object_type or not name:
            return

        normalized_type = object_type.lower().strip()
        normalized_name = name.strip().strip('"')

        objects_set = self._objects_by_type[normalized_type]
        objects_set.add(normalized_name)

        detail_entry: Dict[str, str] = {}
        if details:
            detail_entry.update({k: str(v) for k, v in details.items()})
        if schema:
            detail_entry.setdefault("schema", schema)
            if not self.schema_name:
                self.schema_name = schema
        if detail_entry:
            self._object_details[normalized_type][normalized_name] = detail_entry

        # Maintain backward-compatible buckets
        if normalized_type == "schema":
            self._objects_by_type["schema"].add(normalized_name)
        elif normalized_type == "table":
            self._objects_by_type["table"].add(normalized_name)
        elif normalized_type == "view":
            self._objects_by_type["view"].add(normalized_name)
        elif normalized_type == "function":
            self._objects_by_type["function"].add(normalized_name)
        elif normalized_type == "procedure":
            self._objects_by_type["procedure"].add(normalized_name)
        elif normalized_type == "sequence":
            self._objects_by_type["sequence"].add(normalized_name)
        elif normalized_type == "trigger":
            self._objects_by_type["trigger"].add(normalized_name)

    def add_schema_dropped(self, schema: str) -> None:
        """Backward-compatible helper to add a dropped schema."""
        self.add_cleaned_object("schema", schema)

    def add_table_dropped(self, table: str) -> None:
        """Backward-compatible helper to add a dropped table."""
        self.add_cleaned_object("table", table)

    def add_view_dropped(self, view: str) -> None:
        """Backward-compatible helper to add a dropped view."""
        self.add_cleaned_object("view", view)

    def add_function_dropped(self, function: str) -> None:
        """Backward-compatible helper to add a dropped function."""
        self.add_cleaned_object("function", function)

    def add_procedure_dropped(self, procedure: str) -> None:
        """Backward-compatible helper to add a dropped procedure."""
        self.add_cleaned_object("procedure", procedure)

    def add_sequence_dropped(self, sequence: str) -> None:
        """Backward-compatible helper to add a dropped sequence."""
        self.add_cleaned_object("sequence", sequence)

    def add_trigger_dropped(self, trigger: str) -> None:
        """Backward-compatible helper to add a dropped trigger."""
        self.add_cleaned_object("trigger", trigger)

    @property
    def schemas_dropped(self) -> Set[str]:
        """Set of schema names that were dropped during this clean."""
        return self._objects_by_type["schema"]

    @property
    def tables_dropped(self) -> Set[str]:
        """Set of table names that were dropped during this clean."""
        return self._objects_by_type["table"]

    @property
    def views_dropped(self) -> Set[str]:
        """Set of view names that were dropped during this clean."""
        return self._objects_by_type["view"]

    @property
    def functions_dropped(self) -> Set[str]:
        """Set of function names that were dropped during this clean."""
        return self._objects_by_type["function"]

    @property
    def procedures_dropped(self) -> Set[str]:
        """Set of procedure names that were dropped during this clean."""
        return self._objects_by_type["procedure"]

    @property
    def sequences_dropped(self) -> Set[str]:
        """Set of sequence names that were dropped during this clean."""
        return self._objects_by_type["sequence"]

    @property
    def triggers_dropped(self) -> Set[str]:
        """Set of trigger names that were dropped during this clean."""
        return self._objects_by_type["trigger"]

    def get_objects_by_type(self) -> Dict[str, Set[str]]:
        """Return all cleaned objects grouped by type."""
        return {obj_type: set(names) for obj_type, names in self._objects_by_type.items()}

    def get_object_details(self, object_type: str, name: str) -> Dict[str, str]:
        """Retrieve detail metadata for a cleaned object if available."""
        normalized_type = object_type.lower().strip()
        return self._object_details.get(normalized_type, {}).get(name, {})


class ValidateResult(OperationResult):
    """Result of a validate operation."""

    def __init__(self) -> None:
        """Initialize empty validated/failed migration lists and error counter."""
        super().__init__()
        self.target_schema: str = ""
        self.migration_data: Optional[Any] = None
        self.error_count: int = 0
        self.validated_migrations: List[MigrationInfo] = []
        self.failed_migrations: List[MigrationInfo] = []

    def add_validated_migration(self, migration: MigrationInfo) -> None:
        """Add a validated migration to the result."""
        self.validated_migrations.append(migration)

    def add_failed_migration(self, migration: MigrationInfo) -> None:
        """Add a failed migration to the result."""
        self.failed_migrations.append(migration)
        self.error_count += 1
        self.success = False


class InfoResult(OperationResult):
    """Result of an info operation."""

    def __init__(self) -> None:
        """Initialize an empty info result (migration list + current schema version)."""
        super().__init__()
        self.target_schema: str = ""
        self.migration_data: Optional[Any] = None
        self.current_schema_version: Optional[str] = None
        # ``schema_name`` comes from OperationResult as a property (BUG-06).
        self.migrations: List[MigrationInfo] = []

    def add_migration(self, migration: MigrationInfo) -> None:
        """Add a migration to the result."""
        self.migrations.append(migration)

    @property
    def migrations_applied(self) -> List[str]:
        """Get version strings or script names for successfully applied migrations."""
        applied = []
        for migration in self.migrations:
            if migration.status in ["SUCCESS", "Success"]:
                if migration.version:
                    applied.append(str(migration.version))
                else:
                    applied.append(migration.script)
        return applied

    @property
    def applied_migrations(self) -> List[MigrationInfo]:
        """Get successfully applied migrations for API consumers."""
        return [
            migration for migration in self.migrations if migration.status in ["SUCCESS", "Success"]
        ]

    @property
    def pending_migrations(self) -> List[MigrationInfo]:
        """Get pending migrations for API consumers."""
        return [
            migration for migration in self.migrations if migration.status in ["PENDING", "Pending"]
        ]

    def get_current_version(self) -> Optional[str]:
        """Get the current schema version."""
        return self.current_schema_version


class BaselineResult(OperationResult):
    """Result of a baseline operation."""

    def __init__(self) -> None:
        """Initialize an empty baseline result with placeholder schema/version fields."""
        super().__init__()
        self.target_schema: str = ""
        self.baseline_version: str = ""
        # ``schema_name`` comes from OperationResult as a property (BUG-06).

    def set_baseline_version(self, version: str) -> None:
        """Set the baseline version."""
        self.baseline_version = version


class RepairResult(OperationResult):
    """Result of a repair operation."""

    def __init__(self) -> None:
        """Initialize empty repaired/removed/aligned migration lists and repair counters."""
        super().__init__()
        self.target_schema: str = ""
        # ``schema_name`` comes from OperationResult as a property (BUG-06).
        self.repaired_migrations: List[MigrationInfo] = []
        self.removed_migrations: List[MigrationInfo] = []
        self.aligned_migrations: List[MigrationInfo] = []
        self.checksums_fixed: int = 0
        self.failed_migrations_removed: int = 0
        self.deleted_migrations_marked: int = 0

    def add_repaired_migration(self, migration: MigrationInfo) -> None:
        """Add a repaired migration to the result."""
        self.repaired_migrations.append(migration)

    def add_removed_migration(self, migration: MigrationInfo) -> None:
        """Add a removed migration to the result."""
        self.removed_migrations.append(migration)

    def add_aligned_migration(self, migration: MigrationInfo) -> None:
        """Add an aligned migration to the result."""
        self.aligned_migrations.append(migration)


class SnapshotResult(OperationResult):
    """Result of a snapshot operation."""

    def __init__(
        self,
        success: bool = True,
        error_message: Optional[str] = None,
        output_file: Optional[str] = None,
        snapshot_id: Optional[str] = None,
        captured_at: Optional[str] = None,
    ) -> None:
        """Initialize a snapshot result with file path, snapshot id, and capture timestamp."""
        super().__init__(success=success, error_message=error_message)
        self.output_file: Optional[str] = output_file
        self.snapshot_id: Optional[str] = snapshot_id
        self.captured_at: Optional[str] = captured_at


class UndoResult(OperationResult):
    """Result of an undo operation."""

    def __init__(self) -> None:
        """Initialize empty undo bookkeeping (target version, undone migrations, count)."""
        super().__init__()
        self.target_version: str = ""
        self.target_schema: str = ""
        # ``schema_name`` comes from OperationResult as a property (BUG-06).
        self.current_schema_version: Optional[str] = None
        self.undone_migrations: List[MigrationInfo] = []
        self.undone_count: int = 0

    def add_undone_migration(self, migration: MigrationInfo) -> None:
        """Add an undone migration to the result."""
        self.undone_migrations.append(migration)
        self.undone_count = len(self.undone_migrations)

    @property
    def migrations(self) -> List[MigrationInfo]:
        """Get the undone migrations for HTML template compatibility."""
        return self.undone_migrations


class GenerateUndoScriptResult(OperationResult):
    """Result of generating an undo script."""

    def __init__(self) -> None:
        """Initialize undo-script generation bookkeeping (paths, counts, review flag)."""
        super().__init__()
        self.migration_path: Optional[str] = None
        self.undo_script_path: Optional[str] = None
        self.overwritten: bool = False
        self.statements_generated: int = 0
        self.requires_manual_review: bool = False

    def add_warning(self, warning: str) -> None:
        """Add a warning to the result."""
        super().add_warning(warning)
        if "manual review" in warning.lower() or "warning" in warning.lower():
            self.requires_manual_review = True
