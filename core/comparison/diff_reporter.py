"""Diff Reporter for Human-Readable Output.

This module provides the DiffReporter class which formats diff results
into human-readable reports by delegating to the dblift logging system.

Note: This is a thin wrapper around the core logging formatters (OutputFormatter,
JsonFormatter, HtmlFormatter) to maintain consistency with other dblift commands.
"""

from typing import List, Optional

from core.comparison.diff_models import SchemaDiff, TableDiff
from core.logger import DiffResult, OutputFormatter


class DiffReporter:
    """Generates human-readable diff reports using dblift's logging system.

    This class acts as a bridge between the comparison framework and the
    existing dblift logging/formatting infrastructure, ensuring consistent
    output across all dblift commands.

    Example:
        >>> reporter = DiffReporter()
        >>> result = reporter.create_diff_result(schema_diff)
        >>> text_report = reporter.format(result, format_type="text")
        >>> print(text_report)
    """

    def __init__(self, use_colors: bool = True):
        """Initialize the diff reporter.

        Args:
            use_colors: Whether to use ANSI color codes in text output (not yet implemented)
        """
        self.use_colors = use_colors
        self.formatter = OutputFormatter()

    def create_diff_result(
        self,
        schema_diff: Optional[SchemaDiff] = None,
        table_diffs: Optional[List[TableDiff]] = None,
        comparison_type: str = "schema",
        source_type: str = "script",
        target_type: str = "database",
        target_schema: str = "public",
    ) -> DiffResult:
        """Create a DiffResult from comparison data.

        Args:
            schema_diff: SchemaDiff object containing comparison results
            table_diffs: List of TableDiff objects (for table-only comparisons)
            comparison_type: Type of comparison ("schema" or "table")
            source_type: Source of expected data ("script" or "database")
            target_type: Source of actual data ("script" or "database")
            target_schema: Name of the schema being compared

        Returns:
            DiffResult object ready for formatting
        """
        result = DiffResult()
        result.comparison_type = comparison_type
        result.source_type = source_type
        result.target_type = target_type
        result.target_schema = target_schema

        if schema_diff:
            result.set_schema_diff(schema_diff)

        if table_diffs:
            for table_diff in table_diffs:
                result.add_table_diff(table_diff)

        result.complete()
        return result

    def format(
        self,
        result: DiffResult,
        format_type: str = "text",
        schema_name: Optional[str] = None,
        database_name: Optional[str] = None,
    ) -> str:
        """Format a diff result into the specified format.

        This delegates to the OutputFormatter which handles text, JSON, and HTML
        formats consistently with other dblift commands.

        Args:
            result: DiffResult to format
            format_type: Output format ("text", "json", "html")
            schema_name: Optional schema name for the report
            database_name: Optional database name for the report

        Returns:
            Formatted diff report as a string

        Example:
            >>> report = reporter.format(result, format_type="text")
            >>> json_report = reporter.format(result, format_type="json")
        """
        return self.formatter.format(
            result,
            format_type=format_type,
            schema_name=schema_name or result.target_schema,
            database_name=database_name,
        )

    def format_schema_diff(
        self, schema_diff: SchemaDiff, format_type: str = "text", schema_name: str = "public"
    ) -> str:
        """Convenience method to format a schema diff directly.

        Args:
            schema_diff: SchemaDiff object to format
            format_type: Output format ("text", "json", "html")
            schema_name: Name of the schema

        Returns:
            Formatted diff report

        Example:
            >>> report = reporter.format_schema_diff(diff, format_type="markdown")
        """
        result = self.create_diff_result(
            schema_diff=schema_diff, comparison_type="schema", target_schema=schema_name
        )
        return self.format(result, format_type=format_type, schema_name=schema_name)

    def format_table_diff(
        self, table_diff: TableDiff, format_type: str = "text", schema_name: str = "public"
    ) -> str:
        """Convenience method to format a single table diff directly.

        Args:
            table_diff: TableDiff object to format
            format_type: Output format ("text", "json", "html")
            schema_name: Name of the schema

        Returns:
            Formatted diff report

        Example:
            >>> report = reporter.format_table_diff(diff, format_type="text")
        """
        result = self.create_diff_result(
            table_diffs=[table_diff], comparison_type="table", target_schema=schema_name
        )
        return self.format(result, format_type=format_type, schema_name=schema_name)
