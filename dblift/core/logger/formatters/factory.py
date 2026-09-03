"""Output-formatter factory — selects text/JSON/HTML formatter for operation results."""

from pathlib import Path
from typing import Optional

from dblift.core.logger.formatters.formatter import OutputFormatter
from dblift.core.logger.results import OperationResult


class OutputFormatterFactory:
    """Factory for obtaining output formatters."""

    _formatter = None
    _format_type = "text"
    _schema_name = None
    _database_name = None
    _output_dir = None

    @classmethod
    def configure(
        cls,
        format_type: str = "text",
        schema_name: Optional[str] = None,
        database_name: Optional[str] = None,
        output_dir: Optional[Path] = None,
    ) -> None:
        """Configure the formatter factory.

        Args:
            format_type: Output format type (text, html, json)
            schema_name: Database schema name for reports
            database_name: Database name for reports
            output_dir: Directory to write output files to
        """
        cls._format_type = format_type.lower()
        cls._schema_name = schema_name
        cls._database_name = database_name
        cls._output_dir = output_dir

        # Reset formatter to ensure it's recreated with new settings
        cls._formatter = None

    @classmethod
    def get_formatter(cls, result: OperationResult) -> OutputFormatter:
        """Get a formatter for the operation result.

        Args:
            result: The operation result to format

        Returns:
            A configured OutputFormatter instance
        """
        if cls._formatter is None:
            cls._formatter = OutputFormatter()

        return cls._formatter

    @classmethod
    def format_result(cls, result: OperationResult) -> str:
        """Format a result using the configured formatter.

        Args:
            result: The operation result to format

        Returns:
            Formatted output as a string
        """
        formatter = cls.get_formatter(result)
        output_path = None

        # Create output path if output directory is configured
        if cls._output_dir and cls._format_type in ["html", "json"]:
            command_type = formatter._get_command_type(result)

            # Handle HTML output path
            if (
                cls._format_type == "html"
                and hasattr(formatter, "html_formatter")
                and formatter.html_formatter
            ):
                filename = formatter.html_formatter.get_output_filename(
                    cls._schema_name or "default", cls._database_name or "default", command_type
                )
                output_path = cls._output_dir / filename

            # Handle JSON output path
            elif (
                cls._format_type == "json"
                and hasattr(formatter, "json_formatter")
                and formatter.json_formatter
            ):
                filename = formatter.json_formatter.get_output_filename(
                    cls._schema_name or "default", cls._database_name or "default", command_type
                )
                output_path = cls._output_dir / filename

        # Format the result
        return formatter.format(
            result,
            format_type=cls._format_type,
            schema_name=cls._schema_name,
            database_name=cls._database_name,
            output_path=output_path,
        )
