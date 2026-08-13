"""Migration journal — thread-safe per-migration event log for statements, timings, and failures."""

import re
import threading
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class EntryType(Enum):
    """Type of journal entry"""

    STATEMENT_START = "STATEMENT_START"
    STATEMENT_COMPLETE = "STATEMENT_COMPLETE"
    STATEMENT_FAILED = "STATEMENT_FAILED"
    MIGRATION_START = "MIGRATION_START"
    MIGRATION_COMPLETE = "MIGRATION_COMPLETE"
    MIGRATION_FAILED = "MIGRATION_FAILED"
    OBJECT_CHANGE = "OBJECT_CHANGE"


class JournalEntry:
    """Represents a migration journal entry"""

    def __init__(
        self,
        migration_id: str,
        entry_type: EntryType,
        statement_index: int = 0,
        statement: str = "",
        execution_time: int = 0,
        timestamp: Optional[datetime] = None,
        details: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error_message: str = "",
    ):
        """Initialize a journal entry

        Args:
            migration_id: ID of the migration (typically script_name)
            entry_type: Type of journal entry
            statement_index: Index of SQL statement in migration (0-based)
            statement: SQL statement executed
            execution_time: Time in milliseconds
            timestamp: Time the journal entry was created
            details: Additional details (affected rows, performance metrics)
            success: Whether the operation succeeded
            error_message: Error message if operation failed
        """
        self.migration_id = migration_id
        self.entry_type = entry_type
        self.statement_index = statement_index
        self.statement = statement
        self.execution_time = execution_time
        self.timestamp = timestamp or datetime.now()
        self.details = details or {}
        self.success = success
        self.error_message = error_message


class MigrationJournal:
    """Migration journal for detailed execution tracking

    This class handles tracking migration execution details, including
    SQL statements, performance metrics, and execution status. Data is
    kept in memory for inclusion in log reports rather than written to
    separate files.
    """

    _lock = threading.Lock()  # Thread lock for access

    def __init__(self, enabled: bool = True):
        """Initialize the migration journal

        Args:
            enabled: Whether journaling is enabled
        """
        self.enabled = enabled
        self.current_migration_id: Optional[str] = None
        # Journal data is kept only in memory (no file persistence)

        # In-memory storage for all journal entries
        self.entries: List[JournalEntry] = []

        # Current migration entries
        self._current_entries: List[JournalEntry] = []

        # Map of migration_id to journal entries for quick lookup
        self.migration_journals: Dict[str, List[JournalEntry]] = {}

    def start_migration(self, migration_id: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Start tracking a new migration

        Args:
            migration_id: Migration ID (typically script_name)
            details: Additional migration details
        """
        if not self.enabled:
            return

        # Set current migration ID
        self.current_migration_id = migration_id

        # Create initial entry for migration start
        entry = JournalEntry(
            migration_id=migration_id,
            entry_type=EntryType.MIGRATION_START,
            details=details or {},
            timestamp=datetime.now(),
        )

        self._write_entry(entry)

    def end_migration(
        self,
        migration_id: str,
        success: bool,
        error_message: Optional[str] = None,
        execution_time: int = 0,
    ) -> None:
        """Record the end of a migration.

        Args:
            migration_id: Migration ID (typically script_name)
            success: Whether the migration was successful
            error_message: Optional error message if migration failed
            execution_time: Time taken to execute the migration in milliseconds
        """
        if not self.current_migration_id:
            return

        # Only create an end entry if we have a current migration
        if self.current_migration_id == migration_id:
            entry = JournalEntry(
                migration_id=self.current_migration_id,
                entry_type=EntryType.MIGRATION_COMPLETE if success else EntryType.MIGRATION_FAILED,
                execution_time=execution_time,
                success=success,
                error_message=error_message or "",
                timestamp=datetime.now(),
            )
            self._write_entry(entry)
            # Clear current migration ID
            self.current_migration_id = None

    def record_statement_start(self, statement: str, statement_index: int) -> None:
        """Record start of SQL statement execution

        Args:
            statement: SQL statement being executed
            statement_index: Index of statement in migration (0-based)
        """
        if not self.enabled or not self.current_migration_id:
            return

        entry = JournalEntry(
            migration_id=self.current_migration_id,
            entry_type=EntryType.STATEMENT_START,
            statement=statement,
            statement_index=statement_index,
            timestamp=datetime.now(),
        )

        self._write_entry(entry)

    def record_statement_complete(
        self,
        statement: str,
        statement_index: int,
        execution_time: int,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record completion of SQL statement execution

        Args:
            statement: SQL statement executed
            statement_index: Index of statement in migration (0-based)
            execution_time: Execution time in milliseconds
            details: Additional details (e.g., affected rows)
        """
        if not self.enabled or not self.current_migration_id:
            return

        entry = JournalEntry(
            migration_id=self.current_migration_id,
            entry_type=EntryType.STATEMENT_COMPLETE,
            statement=statement,
            statement_index=statement_index,
            execution_time=execution_time,
            details=details or {},
            timestamp=datetime.now(),
        )

        self._write_entry(entry)

    def record_statement_failed(
        self, statement: str, statement_index: int, error_message: str, execution_time: int = 0
    ) -> None:
        """Record failure of SQL statement execution

        Args:
            statement: SQL statement that failed
            statement_index: Index of statement in migration (0-based)
            error_message: Error message
            execution_time: Execution time in milliseconds
        """
        if not self.enabled or not self.current_migration_id:
            return

        entry = JournalEntry(
            migration_id=self.current_migration_id,
            entry_type=EntryType.STATEMENT_FAILED,
            statement=statement,
            statement_index=statement_index,
            execution_time=execution_time,
            success=False,
            error_message=error_message,
            timestamp=datetime.now(),
        )

        self._write_entry(entry)

    def _write_entry(self, entry: JournalEntry) -> None:
        """Store entry in memory

        Args:
            entry: Journal entry to store
        """
        if not self.enabled:
            return

        with MigrationJournal._lock:
            # Add to in-memory entries
            self.entries.append(entry)

            # Update current migration entries
            if entry.migration_id not in self.migration_journals:
                self.migration_journals[entry.migration_id] = []

            # If this is a migration end entry, remove any existing end entries
            if entry.entry_type in [EntryType.MIGRATION_COMPLETE, EntryType.MIGRATION_FAILED]:
                self.migration_journals[entry.migration_id] = [
                    e
                    for e in self.migration_journals[entry.migration_id]
                    if e.entry_type
                    not in [EntryType.MIGRATION_COMPLETE, EntryType.MIGRATION_FAILED]
                ]
            # For statement entries, ensure we don't have duplicates
            elif entry.entry_type in [EntryType.STATEMENT_START, EntryType.STATEMENT_COMPLETE]:
                # Remove any existing entries for this statement index
                self.migration_journals[entry.migration_id] = [
                    e
                    for e in self.migration_journals[entry.migration_id]
                    if not (
                        e.entry_type == entry.entry_type
                        and e.statement_index == entry.statement_index
                    )
                ]

            # Add new entry to migration journal
            self.migration_journals[entry.migration_id].append(entry)

    def get_migration_journal(self, migration_id: str) -> List[JournalEntry]:
        """Get all journal entries for a migration

        Args:
            migration_id: ID of the migration

        Returns:
            List of journal entries
        """
        if not self.enabled:
            return []

        # Return in-memory journal entries
        return self.migration_journals.get(migration_id, [])

    def record_object_changes(
        self, statement: str, statement_index: int, objects_affected: List[Dict[str, Any]]
    ) -> None:
        """Record objects affected by a SQL statement.

        Args:
            statement: SQL statement executed
            statement_index: Index of statement in migration
            objects_affected: List of affected objects with their metadata
        """
        if not self.enabled or not self.current_migration_id:
            return

        entry = JournalEntry(
            migration_id=self.current_migration_id,
            entry_type=EntryType.OBJECT_CHANGE,
            statement=statement,
            statement_index=statement_index,
            details={"objects_affected": objects_affected},
            timestamp=datetime.now(),
        )

        self._write_entry(entry)

    def _determine_operation_from_statement(
        self, statement: str, object_type: Optional[str] = None
    ) -> str:
        """Determine the operation type from a SQL statement.

        Args:
            statement: SQL statement to analyze
            object_type: Optional object type to help determine operation more accurately

        Returns:
            Operation type (CREATE, ALTER, DROP, INSERT, UPDATE, DELETE, COMMENT, etc.)
        """
        if not statement:
            return "UNKNOWN"

        stmt_upper = statement.strip().upper()

        # Use object type to provide more context when available
        if stmt_upper.startswith("CREATE"):
            # Could be CREATE TABLE, CREATE INDEX, CREATE VIEW, etc.
            # The object_type will help distinguish, but operation is still CREATE
            return "CREATE"
        elif stmt_upper.startswith("ALTER"):
            return "ALTER"
        elif stmt_upper.startswith("DROP"):
            return "DROP"
        elif stmt_upper.startswith("INSERT"):
            return "INSERT"
        elif stmt_upper.startswith("UPDATE"):
            return "UPDATE"
        elif stmt_upper.startswith("DELETE"):
            return "DELETE"
        elif stmt_upper.startswith("COMMENT"):
            return "COMMENT"
        elif stmt_upper.startswith("TRUNCATE"):
            return "TRUNCATE"
        elif stmt_upper.startswith("GRANT"):
            return "GRANT"
        elif stmt_upper.startswith("REVOKE"):
            return "REVOKE"
        elif stmt_upper.startswith("SELECT") or stmt_upper.startswith("WITH"):
            return "SELECT"
        else:
            return "UNKNOWN"

    @staticmethod
    def _normalize_object_type(object_type: Any) -> str:
        """Unwrap enum-like object types to a plain string."""
        if hasattr(object_type, "value"):
            object_type = object_type.value
        return str(object_type)  # lint: allow-enum-str

    @staticmethod
    def _parse_affected_object(obj: Any) -> Tuple[str, str, str]:
        """Return (object_type, object_name, schema) from a dict or SqlObject."""
        if isinstance(obj, dict):
            object_name = obj.get("object_name", "unknown")
            schema = obj.get("schema", "") or ""
            object_type = obj.get("object_type", "UNKNOWN")
        else:
            object_name = getattr(obj, "name", "unknown")
            schema = getattr(obj, "schema", "") or ""
            object_type = getattr(obj, "object_type", "UNKNOWN")
        object_type_str = MigrationJournal._normalize_object_type(object_type)
        object_name_str = str(object_name or "")
        schema_str = str(schema)
        if schema_str and object_name_str.startswith(f"{schema_str}."):
            object_name_str = object_name_str[len(schema_str) + 1 :]
        return object_type_str, object_name_str, schema_str

    @staticmethod
    def _primary_relation_from_select(statement: str) -> str:
        """Return the first FROM relation for a query, or empty if none."""
        match = re.search(
            r"\bFROM\s+(?!\()(?P<name>(?:\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*)"
            r"(?:\s*\.\s*(?:\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*))*)",
            statement or "",
            re.IGNORECASE,
        )
        if not match:
            return ""
        parts = re.split(r"\s*\.\s*", match.group("name"))
        last = parts[-1].strip('"`[]')
        if last.upper() == "DUAL":
            return ""
        return last

    def _object_change_lookups(
        self, entries: List[JournalEntry]
    ) -> Tuple[Dict[int, Any], Dict[str, Any]]:
        """Index first affected object by statement_index, then by SQL text."""
        by_index: Dict[int, Any] = {}
        by_text: Dict[str, Any] = {}
        for entry in entries:
            if entry.entry_type != EntryType.OBJECT_CHANGE or not entry.details:
                continue
            objects_affected = entry.details.get("objects_affected") or []
            if not objects_affected:
                continue
            first = objects_affected[0]
            by_index[entry.statement_index] = first
            if entry.statement:
                by_text.setdefault(entry.statement, first)
        return by_index, by_text

    def _annotate_statement(
        self,
        entry: JournalEntry,
        by_index: Dict[int, Any],
        by_text: Dict[str, Any],
    ) -> Tuple[str, str, str]:
        """Return (operation, object_type, object_name) for a completed statement."""
        obj = by_index.get(entry.statement_index)
        if obj is None:
            obj = by_text.get(entry.statement)
        if obj is not None:
            object_type, object_name, _schema = self._parse_affected_object(obj)
            operation = self._determine_operation_from_statement(entry.statement, object_type)
            return operation, object_type, object_name
        operation = self._determine_operation_from_statement(entry.statement)
        if operation == "SELECT":
            return "SELECT", "QUERY", self._primary_relation_from_select(entry.statement)
        return operation, "", ""

    def get_performance_stats_by_object_type(self, migration_id: str) -> Dict[str, Any]:
        """Get performance statistics grouped by object type.

        Args:
            migration_id: ID of the migration

        Returns:
            Dictionary with performance metrics by object type
        """
        entries = self.get_migration_journal(migration_id)

        if not entries:
            return {}

        # Group statements by object type
        object_stats: Dict[str, Dict[str, Any]] = {}

        for entry in entries:
            # Look for object changes in OBJECT_CHANGE entries
            if entry.entry_type == EntryType.OBJECT_CHANGE and entry.details:
                objects = entry.details.get("objects_affected", [])
                statement_entry = None

                # Find corresponding STATEMENT_COMPLETE entry
                for stmt_entry in entries:
                    if (
                        stmt_entry.entry_type == EntryType.STATEMENT_COMPLETE
                        and stmt_entry.statement_index == entry.statement_index
                    ):
                        statement_entry = stmt_entry
                        break

                if not statement_entry:
                    continue

                # Process each affected object
                for obj in objects:
                    obj_type = obj.get("object_type", "UNKNOWN")
                    obj_name = obj.get("object_name", "")

                    # Initialize stats for this object type if needed
                    if obj_type not in object_stats:
                        object_stats[obj_type] = {
                            "count": 0,
                            "total_time": 0,
                            "max_time": 0,
                            "objects": set(),
                        }

                    # Update stats
                    object_stats[obj_type]["count"] += 1
                    object_stats[obj_type]["total_time"] += statement_entry.execution_time
                    object_stats[obj_type]["max_time"] = max(
                        object_stats[obj_type]["max_time"], statement_entry.execution_time
                    )
                    if obj_name:
                        object_stats[obj_type]["objects"].add(obj_name)

        # Calculate averages and convert sets to lists for JSON serialization
        for obj_type, stats in object_stats.items():
            if stats["count"] > 0:
                stats["avg_time"] = stats["total_time"] / stats["count"]
            stats["objects"] = list(stats["objects"])

        return object_stats

    def get_migration_performance_summary(self, migration_id: str) -> Dict[str, Any]:
        """Get performance summary for a migration

        Args:
            migration_id: ID of the migration

        Returns:
            Dictionary with performance metrics
        """
        entries = self.get_migration_journal(migration_id)

        if not entries:
            return {}

        # Calculate metrics from journal entries
        statement_times = []
        slowest_statement = None
        slowest_time = 0

        # Get migration_id, version and object_operations from entries
        actual_migration_id = ""
        version = None
        object_operations = []

        # First, get migration_id and version from MIGRATION_START entry
        for entry in entries:
            if entry.entry_type == EntryType.MIGRATION_START:
                actual_migration_id = entry.migration_id
                if entry.details:
                    version = entry.details.get("version")
                break
            elif entry.migration_id:
                actual_migration_id = entry.migration_id

        # Then, collect object operations from OBJECT_CHANGE entries
        for entry in entries:
            if entry.entry_type == EntryType.OBJECT_CHANGE and entry.details:
                objects_affected = entry.details.get("objects_affected", [])
                for obj in objects_affected:
                    # Convert SqlObject dict to operation format expected by template
                    if isinstance(obj, dict):
                        object_name = obj.get("object_name", "unknown")
                        schema = obj.get("schema", "")
                        object_type = obj.get("object_type", "UNKNOWN")

                        # Handle object_type enum (generic schema-object type,
                        # not MigrationType). After the .value unwrap above,
                        # object_type is a string in every tested code path.
                        if hasattr(object_type, "value"):
                            object_type = object_type.value
                        object_type_str = str(object_type)  # lint: allow-enum-str

                        # Determine operation more accurately based on statement and object type
                        operation = self._determine_operation_from_statement(
                            entry.statement, object_type_str
                        )

                        # Remove schema prefix from object name if present
                        if schema and object_name.startswith(f"{schema}."):
                            object_name = object_name[len(schema) + 1 :]

                        object_operations.append(
                            {
                                "operation": operation,
                                "object_type": object_type_str,
                                "object_name": object_name,
                                "schema": schema,
                            }
                        )
                    else:
                        # Handle SqlObject instances
                        object_name = getattr(obj, "name", "unknown")
                        schema = getattr(obj, "schema", "")
                        object_type = getattr(obj, "object_type", "UNKNOWN")

                        # Handle object_type enum (generic schema-object type,
                        # not MigrationType). After the .value unwrap above,
                        # object_type is a string in every tested code path.
                        if hasattr(object_type, "value"):
                            object_type = object_type.value
                        object_type_str = str(object_type)  # lint: allow-enum-str

                        # Determine operation more accurately based on statement and object type
                        operation = self._determine_operation_from_statement(
                            entry.statement, object_type_str
                        )

                        # Remove schema prefix from object name if present
                        if schema and object_name.startswith(f"{schema}."):
                            object_name = object_name[len(schema) + 1 :]

                        object_operations.append(
                            {
                                "operation": operation,
                                "object_type": object_type_str,
                                "object_name": object_name,
                                "schema": schema,
                            }
                        )

        for entry in entries:
            if entry.entry_type == EntryType.STATEMENT_COMPLETE:
                statement_times.append(entry.execution_time)

                if entry.execution_time > slowest_time:
                    slowest_time = entry.execution_time
                    slowest_statement = entry.statement

        by_index, by_text = self._object_change_lookups(entries)

        def _statement_dict(entry: JournalEntry) -> Dict[str, Any]:
            operation, object_type, object_name = self._annotate_statement(entry, by_index, by_text)
            return {
                "statement": entry.statement,
                "execution_time": entry.execution_time,
                "details": entry.details,
                "success": entry.success,
                "error": entry.error_message,
                "operation": operation,
                "object_type": object_type,
                "object_name": object_name,
            }

        if not statement_times:
            return {
                "migration_id": actual_migration_id,
                "version": str(version) if version is not None else None,
                "total_statements": 0,
                "total_execution_time": 0,
                "avg_statement_time": 0,
                "max_statement_time": 0,
                "min_statement_time": 0,
                "slowest_statement": None,
                "statements": [],
                "object_operations": object_operations,
            }

        # Calculate summary metrics
        return {
            "migration_id": actual_migration_id,
            "version": str(version) if version is not None else None,
            "total_statements": len(statement_times),
            "total_execution_time": sum(statement_times),
            "avg_statement_time": sum(statement_times) / len(statement_times),
            "max_statement_time": max(statement_times),
            "min_statement_time": min(statement_times),
            "slowest_statement": slowest_statement,
            "statements": [
                _statement_dict(entry)
                for entry in entries
                if entry.entry_type == EntryType.STATEMENT_COMPLETE
            ],
            "object_operations": object_operations,
        }
