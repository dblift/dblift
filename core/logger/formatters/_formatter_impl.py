"""Core ``OutputFormatter`` implementation (non-diff format methods + orchestrator).

The text-diff section helpers live in the ``_format_diff_*.py`` sibling
modules and are mixed in here. The public ``formatter`` façade re-exports
``OutputFormatter`` so existing imports
(``from core.logger.formatters.formatter import OutputFormatter``) keep
working unchanged.

This file was extracted from the monolithic
``core/logger/formatters/formatter.py`` in PR-H11.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Type

from core.logger.formatters._format_diff_meta import _DiffMetaFormatterMixin
from core.logger.formatters._format_diff_object import _DiffObjectFormatterMixin
from core.logger.formatters._format_diff_routine import _DiffRoutineFormatterMixin
from core.logger.formatters._format_diff_table import _DiffTableFormatterMixin
from core.logger.results import (
    BaselineResult,
    CleanResult,
    DiffResult,
    InfoResult,
    MigrateResult,
    OperationResult,
    RepairResult,
    UndoResult,
    ValidateResult,
)

_HTML_FORMATTER_UNLOADED = object()
HtmlFormatter: Any = _HTML_FORMATTER_UNLOADED

try:
    from core.logger.formatters.jsonformatter import JsonFormatter

    JSON_AVAILABLE = True
except ImportError:
    JSON_AVAILABLE = False
    JsonFormatter = None  # type: ignore


class OutputFormatter(
    _DiffMetaFormatterMixin,
    _DiffTableFormatterMixin,
    _DiffRoutineFormatterMixin,
    _DiffObjectFormatterMixin,
):
    """Unified formatter for all operation results."""

    # Maps result type → (format_method_name, command_type_string)
    _RESULT_DISPATCH: Dict[Type[OperationResult], tuple] = {
        MigrateResult: ("format_migrate", "migrate"),
        CleanResult: ("format_clean", "clean"),
        InfoResult: ("format_info", "info"),
        ValidateResult: ("format_validate", "validate"),
        BaselineResult: ("format_baseline", "baseline"),
        RepairResult: ("format_repair", "repair"),
        DiffResult: ("format_diff", "diff"),
        UndoResult: ("format_undo", "undo"),
    }

    def __init__(self) -> None:
        """Initialize the formatter.

        Creates HTML and JSON formatters if available.
        """
        self.html_formatter: Optional[Any] = None
        self.json_formatter: Optional[JsonFormatter] = None

        global HtmlFormatter
        if HtmlFormatter is _HTML_FORMATTER_UNLOADED:
            try:
                from core.logger.formatters.htmlformatter import HtmlFormatter as html_formatter_cls

                HtmlFormatter = html_formatter_cls
            except ImportError:
                HtmlFormatter = None
        if HtmlFormatter is not None:
            self.html_formatter = HtmlFormatter()
        if JSON_AVAILABLE and JsonFormatter is not None:
            self.json_formatter = JsonFormatter()

    def format(
        self,
        result: OperationResult,
        format_type: str = "text",
        schema_name: str = None,
        database_name: str = None,
        output_path: Path = None,
    ) -> str:
        """Format the operation result as a string.

        Args:
            result: The operation result to format
            format_type: Type of formatting to use (text, html, json)
            schema_name: Optional schema name for reports
            database_name: Optional database name for reports
            output_path: Optional path to write output to

        Returns:
            Formatted output as a string
        """
        # Use HTML formatter if requested and available
        if format_type.lower() == "html" and self.html_formatter:
            command_type = self._get_command_type(result)
            return str(
                self.html_formatter.format_result(
                    result,
                    schema_name or "default",
                    database_name or "default",
                    command_type,
                    output_path,
                )
            )

        # Use JSON formatter if requested and available
        if format_type.lower() == "json" and self.json_formatter:
            command_type = self._get_command_type(result)
            return self.json_formatter.format_result(
                result,
                schema_name or "default",
                database_name or "default",
                command_type,
                output_path,
            )

        # Default to text format
        # Set schema_name in result if it's not already set (for tests)
        if schema_name and hasattr(result, "target_schema") and not result.target_schema:
            result.target_schema = schema_name

        for result_type, (method_name, _) in self._RESULT_DISPATCH.items():
            if isinstance(result, result_type):
                return getattr(self, method_name)(result)  # type: ignore[no-any-return]
        return self.format_generic(result)

    def _get_command_type(self, result: OperationResult) -> str:
        """Get the command type from the result object."""
        for result_type, (_, command_type) in self._RESULT_DISPATCH.items():
            if isinstance(result, result_type):
                # command_type is a dispatch-table string constant (MIGRATE,
                # CLEAN, ...), not a MigrationType.
                return str(command_type)  # lint: allow-enum-str
        return "operation"

    def format_generic(self, result: OperationResult) -> str:
        """Format a generic operation result."""
        output = []
        output.append("Operation Report")
        output.append("===============")

        if result.success:
            output.append("Status: SUCCESS")
        else:
            output.append("Status: FAILED")
            if result.error_message:
                output.append(f"Error: {result.error_message}")

        output.append(f"Execution time: {result.execution_time()} ms")

        if result.warnings:
            output.append("\nWarnings:")
            for warning in result.warnings:
                output.append(f"- {warning}")

        self._append_sql_visibility(output, result)
        return "\n".join(output)

    def format_undo(self, result: UndoResult) -> str:
        """Format an undo operation result."""
        output = []
        output.append("Database Undo Report")
        output.append("====================")
        output.append(f"Schema: {result.target_schema}")
        output.append("Status: SUCCESS" if result.success else "Status: FAILED")
        if result.error_message:
            output.append(f"Error: {result.error_message}")
        output.append(f"Execution time: {result.execution_time()} ms")
        output.append("")

        if result.undone_migrations:
            output.append("Migrations Undone:")
            for migration in result.undone_migrations:
                output.append(f"- {migration.script}")
        else:
            output.append("No migrations were undone.")

        self._append_sql_visibility(output, result)
        return "\n".join(output)

    def _append_sql_visibility(self, output: list[str], result: OperationResult) -> None:
        """Append SQL statements only when the operation explicitly requested them."""
        if not getattr(result, "show_sql", False) or not getattr(result, "sql", None):
            return

        output.append("")
        output.append("SQL Statements:")
        output.append("-" * 80)
        for migration_sql in result.sql:
            output.append(f"-- {migration_sql.script}")
            for statement in migration_sql.statements:
                output.append(statement)
        output.append("-" * 80)

    def format_migrate(self, result: MigrateResult) -> str:
        """Format a migrate operation result."""
        output = []
        output.append("Database Migration Report")
        output.append("=======================")
        output.append(f"Schema: {result.target_schema}")

        if result.success and not result.error_message:
            output.append("Status: SUCCESS")
        else:
            output.append("Status: FAILED")
            if result.error_message:
                output.append(f"Error: {result.error_message}")
            else:
                output.append("Error: Unknown error occurred")

        output.append(f"Execution time: {result.execution_time()} ms")
        output.append("")

        # Add migrations table
        if result.migrations:
            output.append("Migrations Executed:")
            output.append("-" * 80)
            output.append(
                f"{'Version':<15}{'Description':<40}{'Type':<15}{'Status':<10}{'Time (ms)':<10}"
            )
            output.append("-" * 80)

            for migration in result.migrations:
                version_str = str(migration.version) if migration.version is not None else "n/a"
                output.append(
                    f"{'V' + version_str:<15}"
                    f"{migration.description:<40}"
                    f"{migration.type:<15}"
                    f"{migration.status:<10}"
                    f"{migration.execution_time:<10}"
                )

            output.append("-" * 80)
        else:
            output.append("No migrations were executed.")

        if result.warnings:
            output.append("\nWarnings:")
            for warning in result.warnings:
                output.append(f"- {warning}")

        self._append_sql_visibility(output, result)
        return "\n".join(output)

    def format_clean(self, result: CleanResult) -> str:
        """Format a clean operation result."""
        output = []
        output.append("Database Clean Report")
        output.append("====================")
        output.append(f"Schema: {result.schema_name}")

        if result.success:
            output.append("Status: SUCCESS")
        else:
            output.append("Status: FAILED")
            if result.error_message:
                output.append(f"Error: {result.error_message}")

        output.append(f"Execution time: {result.execution_time()} ms")
        output.append("")

        if result.schemas_dropped:
            output.append("Schemas dropped:")
            for schema in sorted(result.schemas_dropped):
                output.append(f"- {schema}")
            output.append("")

        if result.tables_dropped:
            output.append("Tables dropped:")
            for table in sorted(result.tables_dropped):
                output.append(f"- {table}")
            output.append("")

        if not result.schemas_dropped and not result.tables_dropped:
            output.append("No schemas or tables were dropped.")

        if result.warnings:
            output.append("\nWarnings:")
            for warning in result.warnings:
                output.append(f"- {warning}")

        return "\n".join(output)

    def format_info(self, result: InfoResult) -> str:
        """Format an info operation result."""
        output = []
        output.append("Database Info Report")
        output.append("===================")
        output.append(f"Schema: {result.schema_name}")

        if result.success:
            output.append("Status: SUCCESS")
        else:
            output.append("Status: FAILED")
            if result.error_message:
                output.append(f"Error: {result.error_message}")

        output.append(f"Current schema version: {result.current_schema_version or 'n/a'}")
        output.append(f"Execution time: {result.execution_time()} ms")
        output.append("")

        if result.migrations:
            output.append("Available Migrations:")
            output.append("-" * 80)
            output.append(f"{'Version':<15}{'Description':<40}{'Type':<15}{'Status':<10}")
            output.append("-" * 80)

            for migration in result.migrations:
                output.append(
                    # Split formatting into shorter segments
                    (
                        f"{(migration.version or 'n/a'):<15}"
                        f"{migration.description:<40}"
                        f"{migration.type:<15}"
                        f"{migration.status:<10}"
                    )
                )

            output.append("-" * 80)
        else:
            output.append("No migrations are available.")

        if result.warnings:
            output.append("\nWarnings:")
            for warning in result.warnings:
                output.append(f"- {warning}")

        return "\n".join(output)

    def format_validate(self, result: ValidateResult) -> str:
        """Format a validate operation result."""
        output = []
        output.append("Database Validation Report")
        output.append("=========================")

        if result.success:
            output.append("Status: SUCCESS")
            output.append("All migrations are properly applied and up to date.")
        else:
            output.append("Status: FAILED")
            output.append(f"Found {result.error_count} validation errors.")
            if result.error_message:
                output.append(f"Error: {result.error_message}")

        output.append(f"Execution time: {result.execution_time()} ms")
        output.append("")

        if result.failed_migrations:
            output.append("Failed Migrations:")
            output.append("-" * 80)
            output.append(f"{'Version':<15}{'Description':<40}{'Type':<15}{'Status':<10}")
            output.append("-" * 80)

            for migration in result.failed_migrations:
                output.append(
                    # Split formatting into shorter segments
                    (
                        f"{(migration.version or 'n/a'):<15}"
                        f"{migration.description:<40}"
                        f"{migration.type:<15}"
                        f"{migration.status:<10}"
                    )
                )

            output.append("-" * 80)

        if result.validated_migrations:
            output.append("Validated Migrations:")
            output.append("-" * 80)
            output.append(f"{'Version':<15}{'Description':<40}{'Type':<15}{'Status':<10}")
            output.append("-" * 80)

            for migration in result.validated_migrations:
                output.append(
                    # Split formatting into shorter segments
                    (
                        f"{(migration.version or 'n/a'):<15}"
                        f"{migration.description:<40}"
                        f"{migration.type:<15}"
                        f"{migration.status:<10}"
                    )
                )

            output.append("-" * 80)

        if result.warnings:
            output.append("\nWarnings:")
            for warning in result.warnings:
                output.append(f"- {warning}")

        return "\n".join(output)

    def format_baseline(self, result: BaselineResult) -> str:
        """Format a baseline operation result."""
        output = []
        output.append("Database Baseline Report")
        output.append("=======================")
        output.append(f"Schema: {result.schema_name}")

        if result.success:
            output.append("Status: SUCCESS")
            output.append(f"Successfully set baseline version to {result.baseline_version}")
        else:
            output.append("Status: FAILED")
            if result.error_message:
                output.append(f"Error: {result.error_message}")

        output.append(f"Execution time: {result.execution_time()} ms")

        if result.warnings:
            output.append("\nWarnings:")
            for warning in result.warnings:
                output.append(f"- {warning}")

        return "\n".join(output)

    def format_repair(self, result: RepairResult) -> str:
        """Format a repair operation result."""
        output = []
        output.append("Database Repair Report")
        output.append("=====================")

        if result.success:
            output.append("Status: SUCCESS")
        else:
            output.append("Status: FAILED")
            if result.error_message:
                output.append(f"Error: {result.error_message}")

        output.append(f"Execution time: {result.execution_time()} ms")
        output.append("")

        if result.repaired_migrations:
            output.append("Repaired Migrations:")
            output.append("-" * 80)
            output.append(f"{'Version':<15}{'Description':<40}{'Type':<15}")
            output.append("-" * 80)

            for migration in result.repaired_migrations:
                output.append(
                    f"{migration.version or 'n/a':<15}{migration.description:<40}{migration.type:<15}"
                )

            output.append("-" * 80)

        if result.removed_migrations:
            output.append("Removed Migrations:")
            output.append("-" * 80)
            output.append(f"{'Version':<15}{'Description':<40}{'Type':<15}")
            output.append("-" * 80)

            for migration in result.removed_migrations:
                output.append(
                    f"{migration.version or 'n/a':<15}{migration.description:<40}{migration.type:<15}"
                )

            output.append("-" * 80)

        if result.aligned_migrations:
            output.append("Aligned Migrations:")
            output.append("-" * 80)
            output.append(f"{'Version':<15}{'Description':<40}{'Type':<15}")
            output.append("-" * 80)

            for migration in result.aligned_migrations:
                output.append(
                    f"{migration.version or 'n/a':<15}{migration.description:<40}{migration.type:<15}"
                )

            output.append("-" * 80)

        if (
            not result.repaired_migrations
            and not result.removed_migrations
            and not result.aligned_migrations
        ):
            output.append("No migrations required repair.")

        if result.warnings:
            output.append("\nWarnings:")
            for warning in result.warnings:
                output.append(f"- {warning}")

        return "\n".join(output)

    def format_diff(self, result: DiffResult) -> str:
        """Format a diff/comparison operation result."""
        sections = [
            self._format_diff_header(result),
            self._format_diff_counts(result),
            self._format_table_diff(result),
            self._format_view_diff(result),
            self._format_index_diff(result),
            self._format_sequence_diff(result),
            self._format_trigger_diff(result),
            self._format_procedure_diff(result),
            self._format_type_diff(result),
            self._format_extension_diff(result),
            self._format_fdw_diff(result),
            self._format_server_diff(result),
            self._format_event_diff(result),
            self._format_diff_footer(result),
        ]
        return "\n".join(s for s in sections if s)
