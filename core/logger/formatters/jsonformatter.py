"""JSON output formatter — serializes operation results to machine-readable JSON files."""

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)

from core.logger.results import (
    CleanResult,
    MigrationInfo,
    OperationResult,
)


class JsonFormatter:
    """JSON formatter for structured log output."""

    def __init__(self):
        """Initialize the JSON formatter."""
        self.log_entries: List[Dict[str, Any]] = []

        # Track multiple commands for multi-command execution
        self.command_results: List[Dict[str, Any]] = []
        self.current_command: Optional[str] = None
        self.using_multi_command = False

    def format_event(self, event) -> str:
        """Format a log event as JSON.

        Args:
            event: The LogEvent to format

        Returns:
            A JSON string representation of the log event (for streaming/debugging)
            Note: For JSON format, events are collected and included in the final result
        """
        # Create a structured log entry
        entry = {
            "timestamp": event.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "level": event.level.value,
            "name": event.component,
            "message": self._sanitize_message(event.message),
        }

        # Add context if available
        if hasattr(event, "context") and event.context:
            entry["context"] = self._sanitize_for_json(event.context)

        # Keep track of this entry for final report
        self.log_entries.append(entry)

        # Return the JSON string (for compatibility, but won't be written to final JSON file)
        return json.dumps(entry, ensure_ascii=False)

    def format_header(self, schema: str = None, database_name: str = None) -> str:
        """Format a header for the JSON log.

        This is a no-op for JSON formatted logs since each line is a complete JSON object.

        Args:
            schema: Optional schema name
            database_name: Optional database name

        Returns:
            An empty string
        """
        return ""

    def format_footer(self) -> str:
        """Format a footer for the JSON log.

        This is a no-op for JSON formatted logs.

        Returns:
            An empty string
        """
        return ""

    def format_result(
        self,
        result: OperationResult,
        schema: str,
        database_name: str,
        command_type: str,
        output_file: Optional[Path] = None,
    ) -> str:
        """Format an operation result as JSON.

        Creates a complete, valid JSON document with all log entries and result summary.

        Args:
            result: The operation result to format
            schema: Schema name
            database_name: Database name
            command_type: Command type (migrate, clean, etc.)
            output_file: Optional path to write the JSON output to

        Returns:
            A JSON string containing the complete log with all entries and result
        """
        execution_time = result.execution_time()

        output: Dict[str, Any] = {}
        output.update(self._get_version_info())
        output.update(self._build_time_metadata(result))
        output.update(self._build_base_metadata(result, schema, database_name))
        output.update(self._format_sql_visibility(result))
        output.update(self._format_migrate_metadata(result, command_type))
        output.update(self._format_clean_metadata(result, command_type))

        total_execution_time, multi_updates = self._format_multi_command_metadata(
            result, schema, database_name, execution_time
        )
        output.update(multi_updates)

        output["execution_time_ms"] = total_execution_time

        return self._serialize_and_write(output, schema, database_name, output_file)

    # ---------------------------------------------------------------------------
    # Private helpers for format_result()
    # ---------------------------------------------------------------------------

    def _get_version_info(self) -> Dict[str, Any]:
        """Return a dict with log_format_version and dblift_version."""
        dblift_version = None

        # Method 1: Try to read from source __init__.py file (most reliable for development)
        try:
            init_file = Path(__file__).parent.parent.parent.parent / "__init__.py"
            if init_file.exists():
                with open(init_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("__version__"):
                            parts = line.split("=", 1)
                            if len(parts) == 2:
                                dblift_version = parts[1].strip().strip('"').strip("'")
                                break
        except Exception as e:
            _logger.debug(f"Could not read version from __init__.py: {e}")

        # Method 2: Try to import directly from package (if source is in path)
        if not dblift_version:
            try:
                import dblift  # type: ignore[import-untyped]

                dblift_version = getattr(dblift, "__version__", None)
            except (ImportError, AttributeError):
                pass

        # Method 3: Fallback to pkg_resources (for installed packages)
        if not dblift_version:
            try:
                import pkg_resources  # type: ignore[import-untyped]

                dblift_version = pkg_resources.get_distribution("dblift").version
            except Exception as e:
                _logger.debug(f"Could not get version from pkg_resources: {e}")

        return {
            "log_format_version": "1.0",
            "dblift_version": dblift_version,
        }

    def _build_time_metadata(self, result: OperationResult) -> Dict[str, Any]:
        """Return a dict with timestamp, start_time and end_time fields."""
        start_time = None
        end_time = None

        if self.using_multi_command and self.command_results:
            # Get start_time from first command
            first_cmd_result = self.command_results[0].get("result")
            if (
                first_cmd_result
                and hasattr(first_cmd_result, "start_time")
                and first_cmd_result.start_time
            ):
                start_time = first_cmd_result.start_time.strftime("%Y-%m-%d %H:%M:%S")
            # Get end_time from last command (or current result)
            if hasattr(result, "end_time") and result.end_time:
                end_time = result.end_time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            if hasattr(result, "start_time") and result.start_time:
                start_time = result.start_time.strftime("%Y-%m-%d %H:%M:%S")
            if hasattr(result, "end_time") and result.end_time:
                end_time = result.end_time.strftime("%Y-%m-%d %H:%M:%S")

        return {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "start_time": start_time,
            "end_time": end_time,
        }

    def _build_base_metadata(
        self, result: OperationResult, schema: str, database_name: str
    ) -> Dict[str, Any]:
        """Return base metadata: schema, database, status, db info, errors, warnings."""
        output: Dict[str, Any] = {
            # Note: "command" field is not included - use "commands" array instead
            "schema": schema or "",
            "database": database_name or "",
            "status": "SUCCESS" if result.success else "FAILED",
            # execution_time_ms will be set later
        }

        # Add database connection info if available
        if hasattr(result, "db_version") and result.db_version:
            output["db_version"] = result.db_version
        if hasattr(result, "native_driver") and result.native_driver:
            output["native_driver"] = result.native_driver
        if hasattr(result, "database_url_masked") and result.database_url_masked:
            output["database_url_masked"] = result.database_url_masked
        if hasattr(result, "server_name") and result.server_name:
            output["server_name"] = result.server_name

        # Add errors if present
        if result.error_message:
            output["error"] = self._sanitize_message(result.error_message)

        # Add warnings if present
        if hasattr(result, "warnings") and result.warnings:
            output["warnings"] = [self._sanitize_message(w) for w in result.warnings]
        else:
            output["warnings"] = []

        return output

    def _format_sql_visibility(self, result: OperationResult) -> Dict[str, Any]:
        """Return structured SQL visibility data when explicitly requested."""
        if not getattr(result, "show_sql", False):
            return {}
        return {
            "show_sql": True,
            "sql": [
                {
                    "script": migration_sql.script,
                    "version": migration_sql.version,
                    "description": migration_sql.description,
                    "statements": [
                        self._sanitize_message(statement) for statement in migration_sql.statements
                    ],
                }
                for migration_sql in getattr(result, "sql", [])
            ],
        }

    def _format_migrate_metadata(
        self, result: OperationResult, command_type: str
    ) -> Dict[str, Any]:
        """Return migrate-specific fields: baseline version, version range, performance."""
        output: Dict[str, Any] = {}

        # Add version information for baseline commands
        if hasattr(result, "init_version") and result.init_version:
            output["version"] = result.init_version
            output["baseline_description"] = (
                result.description if hasattr(result, "description") else "Initial baseline"
            )

        # Add version range for migrate commands
        if (
            command_type == "MIGRATE"
            and hasattr(result, "from_version")
            and hasattr(result, "to_version")
        ):
            output["from_version"] = result.from_version
            output["to_version"] = result.to_version

        # Add performance statistics if journal is available
        if hasattr(result, "journal") and result.journal:
            migration_id = None
            if hasattr(result, "migrations") and result.migrations:
                for migration in result.migrations:
                    if hasattr(migration, "script_name"):
                        migration_id = migration.script_name
                        break

            if migration_id:
                perf_summary = result.journal.get_migration_performance_summary(migration_id)
                if perf_summary:
                    output["performance_summary"] = {
                        "total_statements": perf_summary.get("total_statements", 0),
                        "total_execution_time": perf_summary.get("total_execution_time", 0),
                        "avg_statement_time": perf_summary.get("avg_statement_time", 0),
                        "min_statement_time": perf_summary.get("min_statement_time", 0),
                        "max_statement_time": perf_summary.get("max_statement_time", 0),
                        "slowest_statement": perf_summary.get("slowest_statement", ""),
                    }

                obj_stats = result.journal.get_performance_stats_by_object_type(migration_id)
                if obj_stats:
                    object_performance = []
                    for obj_type, stats in obj_stats.items():
                        object_performance.append(
                            {
                                "object_type": obj_type,
                                "count": stats.get("count", 0),
                                "total_time": stats.get("total_time", 0),
                                "avg_time": stats.get("avg_time", 0),
                            }
                        )
                    output["performance_by_object_type"] = object_performance

        return output

    def _format_clean_metadata(self, result: OperationResult, command_type: str) -> Dict[str, Any]:
        """Return clean-specific fields: objects_dropped."""
        output: Dict[str, Any] = {}

        if self.using_multi_command and self.command_results:
            return output

        if command_type == "CLEAN" and isinstance(result, CleanResult):
            if hasattr(result, "get_objects_by_type"):
                objects_by_type = result.get_objects_by_type()
                if objects_by_type:
                    output["objects_dropped"] = {
                        obj_type: list(obj_names)
                        for obj_type, obj_names in objects_by_type.items()
                        if obj_names
                    }
                else:
                    output["objects_dropped"] = {}
            else:
                output["objects_dropped"] = {}

        return output

    def _format_multi_command_metadata(
        self,
        result: OperationResult,
        schema: str,
        database_name: str,
        execution_time: float,
    ):
        """Return (total_execution_time, dict) for multi-command or single-command mode."""
        total_execution_time: float = float(execution_time)
        output: Dict[str, Any] = {}

        # Note: log_entries are tracked internally but not included in JSON output

        if self.using_multi_command and self.command_results:
            commands_output = []
            total_execution_time = 0.0
            overall_success = True

            for idx, cmd in enumerate(self.command_results, start=1):
                cmd_type = cmd.get("command_type")
                cmd_result: OperationResult = cmd.get("result")  # type: ignore

                # cmd_type is a command-label string constant, not MigrationType.
                cmd_dict = self._format_command_result_data(
                    cmd_result,
                    schema,
                    database_name,
                    str(cmd_type) if cmd_type else "",  # lint: allow-enum-str
                )
                cmd_dict["index"] = idx
                cmd_dict["command"] = cmd_type
                commands_output.append(cmd_dict)

                cmd_execution_time = cmd.get("execution_time", 0)
                if isinstance(cmd_execution_time, (int, float)):
                    total_execution_time += cmd_execution_time

                if not cmd_result.success:
                    overall_success = False

            output["commands"] = commands_output
            output["command_count"] = len(commands_output)
            # `multi_command` mirrors the presence of the `commands` array.
            # Once we entered the multi-command machinery, consumers must parse
            # `commands` regardless of how many entries it holds — including the
            # single-command-via-multi-command case.
            output["multi_command"] = True
            output["status"] = "SUCCESS" if overall_success else "FAILED"
        else:
            output["multi_command"] = False

        return total_execution_time, output

    def _serialize_and_write(
        self,
        data: Dict[str, Any],
        schema: str,
        database_name: str,
        output_file: Optional[Path],
    ) -> str:
        """Serialize data to JSON and optionally write to file."""
        try:
            json_str = json.dumps(data, indent=2, ensure_ascii=False, default=self._json_default)
        except (TypeError, ValueError) as e:
            error_output = {
                "version": "1.0",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "schema": schema or "",
                "database": database_name or "",
                "status": "FAILED",
                "error": f"Failed to serialize JSON log: {str(e)}",
            }
            json_str = json.dumps(error_output, indent=2, ensure_ascii=False, default=str)

        if output_file:
            try:
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(json_str)
            except Exception as e:
                print(f"Warning: Failed to write JSON log to file: {e}", file=sys.stderr)

        return json_str

    def add_log_entry(self, level: str, component: str, message: str) -> None:
        """Add a log entry to track in the formatter.

        Args:
            level: Log level (DEBUG, INFO, etc.)
            component: Component name
            message: Log message
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_entries.append(
            {"timestamp": timestamp, "level": level, "name": component, "message": message}
        )

    def set_current_command(self, command_type: str) -> None:
        """Set the current command being executed in a multi-command scenario.

        Args:
            command_type: The type of command being executed (e.g., 'MIGRATE', 'INFO')
        """
        self.current_command = command_type
        self.using_multi_command = True

    def add_command_result(self, command_type: str, result: OperationResult) -> None:
        """Add a command result in a multi-command scenario.

        Args:
            command_type: The type of command executed (e.g., 'MIGRATE', 'INFO')
            result: The operation result
        """
        self.command_results.append(
            {
                "command_type": command_type,
                "result": result,
                "success": result.success,
                "error_message": result.error_message,
                "execution_time": result.execution_time(),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    def set_multi_command_mode(self, enabled: bool = True) -> None:
        """Enable or disable multi-command mode for logging.

        Args:
            enabled: Whether to enable multi-command mode
        """
        self.using_multi_command = enabled

    def _format_command_result_data(
        self, result: OperationResult, schema: str, database_name: str, command_type: str
    ) -> Dict[str, Any]:
        """Format command-specific result data for a single command in multi-command scenario.

        Args:
            result: The operation result to format
            schema: Schema name
            database_name: Database name
            command_type: Command type (migrate, clean, etc.)

        Returns:
            A dictionary containing the command result data
        """
        execution_time = result.execution_time()

        cmd_output: Dict[str, Any] = {
            "command": command_type,
            "schema": schema or "",
            "database": database_name or "",
            "status": "SUCCESS" if result.success else "FAILED",
            "execution_time_ms": execution_time,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        # Add errors if present
        if result.error_message:
            cmd_output["error"] = self._sanitize_message(result.error_message)

        # Add warnings if present
        if hasattr(result, "warnings") and result.warnings:
            cmd_output["warnings"] = [self._sanitize_message(w) for w in result.warnings]
        else:
            cmd_output["warnings"] = []

        # Add migration-specific information for commands that have migrations
        if hasattr(result, "migrations") and result.migrations:
            # Convert migration objects to dictionaries using the helper method
            migrations = []
            for migration in result.migrations:
                if isinstance(migration, MigrationInfo):
                    migration_dict = self._migration_to_dict(migration)
                else:
                    # Fallback for non-MigrationInfo objects
                    migration_dict = {}
                    for attr in [
                        "script",
                        "version",
                        "description",
                        "type",
                        "status",
                        "execution_time",
                        "installed_on",
                        "installed_by",
                        "checksum",
                        "error",
                    ]:
                        if hasattr(migration, attr):
                            value = getattr(migration, attr)
                            # Handle datetime objects
                            if isinstance(value, datetime):
                                migration_dict[attr] = value.strftime("%Y-%m-%d %H:%M:%S")
                            else:
                                migration_dict[attr] = self._sanitize_for_json(value)
                migrations.append(migration_dict)
            cmd_output["migrations"] = migrations
            cmd_output["migration_count"] = len(migrations)
        else:
            cmd_output["migrations"] = []
            cmd_output["migration_count"] = 0

        cmd_output.update(self._format_sql_visibility(result))

        # Add version information for baseline commands
        if hasattr(result, "init_version") and result.init_version:
            cmd_output["version"] = result.init_version
            cmd_output["baseline_description"] = (
                result.description if hasattr(result, "description") else "Initial baseline"
            )

        # Add version range for migrate commands
        if (
            command_type == "MIGRATE"
            and hasattr(result, "from_version")
            and hasattr(result, "to_version")
        ):
            cmd_output["from_version"] = result.from_version
            cmd_output["to_version"] = result.to_version

        # For clean command, add all objects dropped
        if command_type == "CLEAN" and isinstance(result, CleanResult):
            # Include the comprehensive objects_by_type grouped by type
            if hasattr(result, "get_objects_by_type"):
                objects_by_type = result.get_objects_by_type()
                if objects_by_type:
                    # Convert sets to lists for JSON serialization
                    cmd_output["objects_dropped"] = {
                        obj_type: list(obj_names)
                        for obj_type, obj_names in objects_by_type.items()
                        if obj_names
                    }
                else:
                    cmd_output["objects_dropped"] = {}
            else:
                cmd_output["objects_dropped"] = {}

        return cmd_output

    def _migration_to_dict(self, migration: MigrationInfo) -> Dict[str, Any]:
        """Convert a MigrationInfo object to a dictionary."""
        # Handle installed_on which can be datetime or string (e.g., from CosmosDB)
        installed_on_value = None
        if migration.installed_on:
            if isinstance(migration.installed_on, str):
                # Already a string (e.g., ISO format from CosmosDB)
                installed_on_value = migration.installed_on
            elif hasattr(migration.installed_on, "isoformat"):
                # It's a datetime object
                installed_on_value = migration.installed_on.isoformat()
            else:
                # Fallback: convert to string
                installed_on_value = str(migration.installed_on)

        return {
            "script": migration.script,
            "version": migration.version,
            "description": migration.description,
            "type": migration.type,
            "status": migration.status,
            "installed_on": installed_on_value,
            "installed_by": migration.installed_by,
            "checksum": migration.checksum,
            "execution_time": migration.execution_time,
            "error": migration.error,
        }

    def get_output_filename(self, schema_name: str, database_name: str, command_type: str) -> str:
        """Generate a filename for the JSON report.

        Args:
            schema_name: Database schema name
            database_name: Database name
            command_type: Command type (migrate, clean, etc.)

        Returns:
            String containing the filename
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"Dblift_{schema_name}_{database_name}_{command_type}_{timestamp}.json"

    def _sanitize_message(self, message: str) -> str:
        """Sanitize a log message to ensure it's JSON-safe.

        Args:
            message: The message to sanitize

        Returns:
            A sanitized message string
        """
        if not isinstance(message, str):
            return str(message)
        # Remove control characters except newlines and tabs
        # Keep newlines and tabs, remove other control chars
        sanitized = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]", "", message)
        return sanitized

    def _sanitize_for_json(self, obj: Any) -> Any:
        """Recursively sanitize an object to ensure it's JSON-serializable.

        Args:
            obj: The object to sanitize

        Returns:
            A JSON-serializable version of the object
        """
        if isinstance(obj, dict):
            return {k: self._sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._sanitize_for_json(item) for item in obj]
        elif isinstance(obj, str):
            return self._sanitize_message(obj)
        elif isinstance(obj, (int, float, bool, type(None))):
            return obj
        elif isinstance(obj, datetime):
            return obj.strftime("%Y-%m-%d %H:%M:%S")
        else:
            # Convert to string as fallback
            return str(obj)

    def _json_default(self, obj: Any) -> Any:
        """Default JSON serializer for non-serializable objects.

        Args:
            obj: Object to serialize

        Returns:
            A JSON-serializable representation
        """
        if isinstance(obj, datetime):
            return obj.strftime("%Y-%m-%d %H:%M:%S")
        elif hasattr(obj, "__dict__"):
            return obj.__dict__
        else:
            return str(obj)

    def _count_log_levels(self) -> Dict[str, int]:
        """Count log entries by level.

        Returns:
            Dictionary with counts for each log level
        """
        counts: Dict[str, int] = {}
        for entry in self.log_entries:
            level = entry.get("level", "UNKNOWN")
            counts[level] = counts.get(level, 0) + 1
        return counts
