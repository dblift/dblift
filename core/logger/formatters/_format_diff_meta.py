"""Header, counts summary, and footer sections of the text diff report.

Extracted from ``core/logger/formatters/formatter.py`` (PR-H11) as part of
the per-format sibling split. The mixin is consumed by
``OutputFormatter`` so the bound-method call sites (``self._format_diff_header``)
continue to work unchanged.
"""

from core.logger.results import DiffResult


class _DiffMetaFormatterMixin:
    """Mixin providing report header, summary-counts, and footer sections."""

    def _format_diff_header(self, result: DiffResult) -> str:
        """Format diff report header with schema info and status."""
        lines = []
        lines.append("Schema Comparison Report")
        lines.append("=" * 80)

        if result.schema_diff:
            schema_name = result.schema_diff.schema_name or result.target_schema or "unknown"
            lines.append(f"\nSchema: {schema_name}")
            lines.append(f"Source: {result.source_type}")
            lines.append(f"Target: {result.target_type}")

            if result.success:
                lines.append(
                    f"\nStatus: ✓ No critical differences ({result.total_differences} total)"
                )
            else:
                lines.append(f"\nStatus: ✗ {result.error_count} critical difference(s) found")

        return "\n".join(lines)

    def _format_diff_counts(self, result: DiffResult) -> str:
        """Format summary counts table for all object types."""
        if not result.schema_diff:
            return ""
        lines = []
        lines.append("\nSummary:")
        lines.append(f"  Missing Tables:  {len(result.missing_tables)}")
        lines.append(f"  Extra Tables:    {len(result.extra_tables)}")
        lines.append(f"  Modified Tables: {len(result.schema_diff.modified_tables)}")
        lines.append(f"  Missing Views:   {len(result.missing_views)}")
        lines.append(f"  Extra Views:     {len(result.extra_views)}")
        lines.append(f"  Modified Views:  {len(result.schema_diff.modified_views)}")
        lines.append(f"  Missing Indexes: {len(result.missing_indexes)}")
        lines.append(f"  Extra Indexes:   {len(result.extra_indexes)}")
        lines.append(f"  Modified Indexes: {len(result.schema_diff.modified_indexes)}")
        lines.append(f"  Missing Sequences: {len(result.missing_sequences)}")
        lines.append(f"  Extra Sequences:   {len(result.extra_sequences)}")
        lines.append(
            f"  Modified Sequences: {len(getattr(result.schema_diff, 'modified_sequences', []))}"
        )
        lines.append(f"  Missing Triggers: {len(getattr(result, 'missing_triggers', []))}")
        lines.append(f"  Extra Triggers:   {len(getattr(result, 'extra_triggers', []))}")
        lines.append(
            f"  Modified Triggers: {len(getattr(result.schema_diff, 'modified_triggers', []))}"
        )
        lines.append(f"  Missing Procedures: {len(getattr(result, 'missing_procedures', []))}")
        lines.append(f"  Extra Procedures:   {len(getattr(result, 'extra_procedures', []))}")
        lines.append(
            f"  Modified Procedures: {len(getattr(result.schema_diff, 'modified_procedures', []))}"
        )
        lines.append(f"  Missing Functions: {len(getattr(result, 'missing_functions', []))}")
        lines.append(f"  Extra Functions:   {len(getattr(result, 'extra_functions', []))}")
        lines.append(
            f"  Modified Functions: {len(getattr(result.schema_diff, 'modified_functions', []))}"
        )
        lines.append(
            f"  Missing User-Defined Types: {len(getattr(result, 'missing_user_defined_types', []))}"
        )
        lines.append(
            f"  Extra User-Defined Types:   {len(getattr(result, 'extra_user_defined_types', []))}"
        )
        lines.append(
            f"  Modified User-Defined Types: {len(getattr(result.schema_diff, 'modified_user_defined_types', []))}"
        )
        lines.append(f"  Missing Extensions: {len(result.missing_extensions)}")
        lines.append(f"  Extra Extensions:   {len(result.extra_extensions)}")
        lines.append(
            f"  Modified Extensions: {len(getattr(result.schema_diff, 'modified_extensions', []))}"
        )
        lines.append(
            f"  Missing Foreign Data Wrappers: {len(result.missing_foreign_data_wrappers)}"
        )
        lines.append(f"  Extra Foreign Data Wrappers:   {len(result.extra_foreign_data_wrappers)}")
        lines.append(
            "  Modified Foreign Data Wrappers: "
            f"{len(getattr(result.schema_diff, 'modified_foreign_data_wrappers', []))}"
        )
        lines.append(f"  Missing Foreign Servers: {len(result.missing_foreign_servers)}")
        lines.append(f"  Extra Foreign Servers:   {len(result.extra_foreign_servers)}")
        lines.append(
            f"  Modified Foreign Servers: {len(getattr(result.schema_diff, 'modified_foreign_servers', []))}"
        )
        lines.append(f"  Missing Events: {len(result.missing_events)}")
        lines.append(f"  Extra Events:   {len(result.extra_events)}")
        lines.append(
            f"  Modified Events: {len(getattr(result.schema_diff, 'modified_events', []))}"
        )
        lines.append(f"  Total Diffs:     {result.total_differences}")
        return "\n".join(lines)

    def _format_diff_footer(self, result: DiffResult) -> str:
        """Format diff report footer with execution time and warnings."""
        lines = []
        lines.append("\n" + "=" * 80)
        lines.append(f"Execution time: {result.execution_time()} ms")

        if result.warnings:
            lines.append("\nWarnings:")
            for warning in result.warnings:
                lines.append(f"- {warning}")

        return "\n".join(lines)
