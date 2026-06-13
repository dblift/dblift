"""Operation result containers returned by the command layer.

Each ``*Result`` class subclasses :class:`OperationResult` and carries the
typed payload (migrations applied, objects dropped, diff buckets, ...) that
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


class DiffResult(OperationResult):
    """Result of a schema comparison/drift detection operation."""

    def __init__(self) -> None:
        """Initialize empty per-object-type diff buckets and counters used by formatters."""
        super().__init__()
        self.schema_diff: Optional[Any] = None  # SchemaDiff object
        self.table_diffs: List[Any] = []  # List of TableDiff objects
        self.comparison_type: str = "schema"  # "schema" or "table"
        self.source_type: str = "script"  # "script" or "database"
        self.target_type: str = "database"  # "script" or "database"
        self.expected_payload: Optional[Any] = None  # Expected schema payload (for SQL generation)
        self.total_differences: int = 0
        self.error_count: int = 0
        self.warning_count: int = 0
        self.info_count: int = 0
        self.missing_tables: List[str] = []
        self.extra_tables: List[str] = []
        self.modified_tables: List[str] = []

        # View diffs
        self.missing_views: List[str] = []
        self.extra_views: List[str] = []
        self.modified_views: List[str] = []

        # Index diffs
        self.missing_indexes: List[str] = []
        self.extra_indexes: List[str] = []
        self.modified_indexes: List[str] = []

        # Sequence diffs
        self.missing_sequences: List[str] = []
        self.extra_sequences: List[str] = []
        self.modified_sequences: List[str] = []

        # Trigger diffs
        self.missing_triggers: List[str] = []
        self.extra_triggers: List[str] = []
        self.modified_triggers: List[str] = []

        # Procedures
        self.missing_procedures: List[str] = []
        self.extra_procedures: List[str] = []
        self.modified_procedures: List[str] = []

        # Functions
        self.missing_functions: List[str] = []
        self.extra_functions: List[str] = []
        self.modified_functions: List[str] = []

        # User-defined types
        self.missing_user_defined_types: List[str] = []
        self.extra_user_defined_types: List[str] = []
        self.modified_user_defined_types: List[str] = []

        # Extensions
        self.missing_extensions: List[str] = []
        self.extra_extensions: List[str] = []
        self.modified_extensions: List[str] = []

        # Foreign data wrappers and servers
        self.missing_foreign_data_wrappers: List[str] = []
        self.extra_foreign_data_wrappers: List[str] = []
        self.modified_foreign_data_wrappers: List[str] = []

        self.missing_foreign_servers: List[str] = []
        self.extra_foreign_servers: List[str] = []
        self.modified_foreign_servers: List[str] = []

        # Events
        self.missing_events: List[str] = []
        self.extra_events: List[str] = []
        self.modified_events: List[str] = []

        # Unmanaged objects (for brownfield databases)
        self.unmanaged_tables: List[str] = []
        self.unmanaged_views: List[str] = []
        self.unmanaged_procedures: List[str] = []
        self.unmanaged_functions: List[str] = []
        self.unmanaged_triggers: List[str] = []
        self.has_unmanaged_objects: bool = False

    def set_schema_diff(self, schema_diff: Any) -> None:
        """Set the schema diff and calculate counts.

        Args:
            schema_diff: SchemaDiff object containing comparison results
        """
        self.schema_diff = schema_diff

        # If schema_diff is None or falsy, set success=True (no drift)
        if not schema_diff:
            self.success = True
            self.total_differences = 0
            return

        if schema_diff:
            self.missing_tables = list(schema_diff.missing_tables)
            self.extra_tables = list(schema_diff.extra_tables)
            self.modified_tables = [t.table_name for t in schema_diff.modified_tables]

            # Extract view diffs
            self.missing_views = list(getattr(schema_diff, "missing_views", []))
            self.extra_views = list(getattr(schema_diff, "extra_views", []))
            self.modified_views = [v.view_name for v in getattr(schema_diff, "modified_views", [])]

            # Extract index diffs
            self.missing_indexes = list(getattr(schema_diff, "missing_indexes", []))
            self.extra_indexes = list(getattr(schema_diff, "extra_indexes", []))
            self.modified_indexes = [
                i.index_name for i in getattr(schema_diff, "modified_indexes", [])
            ]

            # Extract sequence diffs
            self.missing_sequences = list(getattr(schema_diff, "missing_sequences", []))
            self.extra_sequences = list(getattr(schema_diff, "extra_sequences", []))
            self.modified_sequences = [
                s.sequence_name for s in getattr(schema_diff, "modified_sequences", [])
            ]

            # Extract trigger diffs
            self.missing_triggers = list(getattr(schema_diff, "missing_triggers", []))
            self.extra_triggers = list(getattr(schema_diff, "extra_triggers", []))
            self.modified_triggers = [
                t.trigger_name for t in getattr(schema_diff, "modified_triggers", [])
            ]

            # Procedures
            self.missing_procedures = list(getattr(schema_diff, "missing_procedures", []))
            self.extra_procedures = list(getattr(schema_diff, "extra_procedures", []))
            self.modified_procedures = [
                p.procedure_name for p in getattr(schema_diff, "modified_procedures", [])
            ]

            # Functions
            self.missing_functions = list(getattr(schema_diff, "missing_functions", []))
            self.extra_functions = list(getattr(schema_diff, "extra_functions", []))
            self.modified_functions = [
                f.function_name for f in getattr(schema_diff, "modified_functions", [])
            ]

            # User-defined types
            self.missing_user_defined_types = list(
                getattr(schema_diff, "missing_user_defined_types", [])
            )
            self.extra_user_defined_types = list(
                getattr(schema_diff, "extra_user_defined_types", [])
            )
            self.modified_user_defined_types = [
                udt.type_name for udt in getattr(schema_diff, "modified_user_defined_types", [])
            ]

            # Extensions
            self.missing_extensions = list(getattr(schema_diff, "missing_extensions", []))
            self.extra_extensions = list(getattr(schema_diff, "extra_extensions", []))
            self.modified_extensions = [
                ext.extension_name for ext in getattr(schema_diff, "modified_extensions", [])
            ]

            # Foreign data wrappers and servers
            self.missing_foreign_data_wrappers = list(
                getattr(schema_diff, "missing_foreign_data_wrappers", [])
            )
            self.extra_foreign_data_wrappers = list(
                getattr(schema_diff, "extra_foreign_data_wrappers", [])
            )
            self.modified_foreign_data_wrappers = [
                fdw.wrapper_name
                for fdw in getattr(schema_diff, "modified_foreign_data_wrappers", [])
            ]

            self.missing_foreign_servers = list(getattr(schema_diff, "missing_foreign_servers", []))
            self.extra_foreign_servers = list(getattr(schema_diff, "extra_foreign_servers", []))
            self.modified_foreign_servers = [
                server.server_name
                for server in getattr(schema_diff, "modified_foreign_servers", [])
            ]

            # Events
            self.missing_events = list(getattr(schema_diff, "missing_events", []))
            self.extra_events = list(getattr(schema_diff, "extra_events", []))
            self.modified_events = [
                event.event_name for event in getattr(schema_diff, "modified_events", [])
            ]

            self.total_differences = schema_diff.get_total_diff_count()

            # Calculate severity counts
            self.error_count = 0
            self.warning_count = 0
            self.info_count = 0

            # Count by severity
            from core.comparison.diff_models import DiffSeverity

            if schema_diff.severity == DiffSeverity.ERROR:
                self.error_count = self.total_differences
            elif schema_diff.severity == DiffSeverity.WARNING:
                self.warning_count = self.total_differences
            else:
                self.info_count = self.total_differences

            # Set success based on whether there are any differences
            # Drift detection should fail on any managed object differences (ERROR, WARNING, or INFO)
            if self.total_differences > 0:
                self.success = False
                if self.error_count > 0:
                    self.error_message = f"Found {self.error_count} critical differences"
                elif self.warning_count > 0:
                    self.error_message = f"Found {self.warning_count} schema differences"
                else:
                    self.error_message = f"Found {self.info_count} informational differences"
            else:
                self.success = True

    def add_table_diff(self, table_diff: Any) -> None:
        """Add a table diff to the result.

        Args:
            table_diff: TableDiff object to add
        """
        self.table_diffs.append(table_diff)

    def set_unmanaged_objects(
        self,
        tables: List[str] = None,
        views: List[str] = None,
        procedures: List[str] = None,
        functions: List[str] = None,
        triggers: List[str] = None,
    ) -> None:
        """Set unmanaged objects detected in database.

        Args:
            tables: List of unmanaged table names
            views: List of unmanaged view names
            procedures: List of unmanaged procedure names
            functions: List of unmanaged function names
            triggers: List of unmanaged trigger names
        """
        self.unmanaged_tables = tables or []
        self.unmanaged_views = views or []
        self.unmanaged_procedures = procedures or []
        self.unmanaged_functions = functions or []
        self.unmanaged_triggers = triggers or []

        # Set flag if any unmanaged objects exist
        self.has_unmanaged_objects = bool(
            self.unmanaged_tables
            or self.unmanaged_views
            or self.unmanaged_procedures
            or self.unmanaged_functions
            or self.unmanaged_triggers
        )

    def get_unmanaged_count(self) -> int:
        """Get total count of unmanaged objects.

        Returns:
            Total number of unmanaged objects
        """
        return (
            len(self.unmanaged_tables)
            + len(self.unmanaged_views)
            + len(self.unmanaged_procedures)
            + len(self.unmanaged_functions)
            + len(self.unmanaged_triggers)
        )


class ExportSchemaResult(OperationResult):
    """Result of an export schema operation."""

    def __init__(
        self,
        success: bool = True,
        error_message: Optional[str] = None,
        output_files: Optional[List[str]] = None,
        objects_exported: Optional[Dict[str, int]] = None,
    ) -> None:
        """Initialize export-schema bookkeeping (output files, per-type counts, filters)."""
        super().__init__(success=success, error_message=error_message)
        self.output_files: List[str] = output_files or []
        self.objects_exported: Dict[str, int] = objects_exported or {}
        self.current_schema_version: Optional[str] = None
        self.filters_applied: Optional[List[str]] = None
        self.output_options: Optional[Dict[str, Any]] = None


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


class PlanResult(OperationResult):
    """Result of an offline migration plan operation."""

    def __init__(self) -> None:
        """Initialize empty plan bookkeeping."""
        super().__init__()
        self.snapshot_model: Optional[str] = None
        self.target_last_version: Optional[str] = None
        self.target_installed_rank: Optional[int] = None
        self.pending_migrations: List[Any] = []
        self.repeatables_pending: List[Any] = []
        self.checksum_drift: List[Any] = []
        self.already_applied_count: int = 0
        self.sql_validation: Optional[Any] = None
        self.plan_warnings: List[str] = []
        self.plan_errors: List[str] = []

    @property
    def pending_count(self) -> int:
        """Number of pending versioned migrations."""
        return len(self.pending_migrations)

    @property
    def repeatables_pending_count(self) -> int:
        """Number of repeatable migrations selected by the plan."""
        return len(self.repeatables_pending)

    @property
    def checksum_drift_count(self) -> int:
        """Number of applied versioned migrations with checksum drift."""
        return len(self.checksum_drift)

    @property
    def is_sql_validation_only_failure(self) -> bool:
        """True when the only plan failure is SQL-validation findings.

        Lets the preflight orchestrator distinguish a soft sql-validation
        failure (non-blocking under ``--fail-on warning``) from hard errors
        like checksum drift or runtime exceptions, without comparing raw
        error-message strings.
        """
        if self.error_message or self.checksum_drift:
            return False
        if not self.plan_errors:
            return False
        from core.migration.planning.models import SQL_VALIDATION_FAILURE_MESSAGE

        return all(error == SQL_VALIDATION_FAILURE_MESSAGE for error in self.plan_errors)

    def refresh_success(self) -> None:
        """Refresh success after mutating plan errors or drift lists."""
        self.success = not bool(self.plan_errors or self.checksum_drift)

    def apply_plan_data(self, plan: Any) -> None:
        """Copy a planning-layer payload into this operation result."""
        self.snapshot_model = plan.snapshot_model
        self.target_last_version = plan.target_last_version
        self.target_installed_rank = plan.target_installed_rank
        self.pending_migrations = list(plan.pending)
        self.repeatables_pending = list(plan.repeatables_pending)
        self.checksum_drift = list(plan.checksum_drift)
        self.already_applied_count = plan.already_applied_count
        self.sql_validation = plan.sql_validation
        self.plan_warnings = list(plan.warnings)
        self.plan_errors = list(plan.errors)
        for warning in self.plan_warnings:
            self.add_warning(warning)
        self.refresh_success()


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


class GenerateSqlFromDiffResult(OperationResult):
    """Result of generating SQL script from schema diff."""

    def __init__(self) -> None:
        """Initialize SQL-from-diff result bookkeeping (script, path, summary, review flag)."""
        super().__init__()
        self.sql_script: Optional[str] = None
        self.sql_file_path: Optional[str] = None
        self.statements_generated: int = 0
        self.requires_manual_review: bool = False
        self.diff_summary: Optional[Dict[str, Any]] = None

    def add_warning(self, warning: str) -> None:
        """Add a warning to the result."""
        super().add_warning(warning)
        if "manual review" in warning.lower() or "warning" in warning.lower():
            self.requires_manual_review = True
