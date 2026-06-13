"""Table-like diff sections (tables, views, indexes, sequences) for the text report.

Extracted from ``core/logger/formatters/formatter.py`` (PR-H11) as part of
the per-format sibling split. The mixin is consumed by
``OutputFormatter`` so the bound-method call sites continue to work
unchanged.
"""

from core.logger.results import DiffResult


class _DiffTableFormatterMixin:
    """Mixin providing table/view/index/sequence diff section formatters."""

    def _format_table_diff(self, result: DiffResult) -> str:
        """Format tables diff section."""
        if not result.schema_diff:
            return ""
        if not (result.missing_tables or result.extra_tables or result.schema_diff.modified_tables):
            return ""
        lines = []

        if result.missing_tables:
            lines.append(f"\nMissing Tables ({len(result.missing_tables)}):")
            for table in result.missing_tables:
                lines.append(f"  - {table}")

        if result.extra_tables:
            lines.append(f"\nExtra Tables ({len(result.extra_tables)}):")
            for table in result.extra_tables:
                lines.append(f"  + {table}")

        if result.schema_diff.modified_tables:
            lines.append(f"\nModified Tables ({len(result.schema_diff.modified_tables)}):")
            for table_diff in result.schema_diff.modified_tables:
                lines.append(
                    f"\n  Table: {table_diff.table_name} [{table_diff.severity.value.upper()}]"
                )
                lines.append("  " + "-" * 60)

                if table_diff.missing_columns:
                    lines.append(f"    Missing Columns ({len(table_diff.missing_columns)}):")
                    for col in table_diff.missing_columns:
                        lines.append(f"      - {col}")

                if table_diff.extra_columns:
                    lines.append(f"    Extra Columns ({len(table_diff.extra_columns)}):")
                    for col in table_diff.extra_columns:
                        lines.append(f"      + {col}")

                if table_diff.modified_columns:
                    lines.append(f"    Modified Columns ({len(table_diff.modified_columns)}):")
                    for col_diff in table_diff.modified_columns:
                        severity_symbol = "✗" if col_diff.severity.value == "error" else "⚠"
                        lines.append(f"      {severity_symbol} {col_diff.column_name}:")

                        if col_diff.data_type_diff:
                            lines.append(
                                f"         type: {col_diff.data_type_diff[0]} → {col_diff.data_type_diff[1]}"
                            )
                        if col_diff.nullable_diff is not None:
                            lines.append(
                                f"         nullable: {col_diff.nullable_diff[0]} → {col_diff.nullable_diff[1]}"
                            )
                        if col_diff.default_diff:
                            lines.append(
                                f"         default: {col_diff.default_diff[0]} → {col_diff.default_diff[1]}"
                            )
                        if col_diff.identity_diff is not None:
                            lines.append(
                                f"         identity: {col_diff.identity_diff[0]} → {col_diff.identity_diff[1]}"
                            )
                        if col_diff.computed_diff:
                            lines.append(
                                f"         computed: {col_diff.computed_diff[0]} → {col_diff.computed_diff[1]}"
                            )

                if table_diff.missing_constraints:
                    lines.append(
                        f"    Missing Constraints ({len(table_diff.missing_constraints)}):"
                    )
                    for const in table_diff.missing_constraints:
                        lines.append(f"      - {const}")

                if table_diff.extra_constraints:
                    lines.append(f"    Extra Constraints ({len(table_diff.extra_constraints)}):")
                    for const in table_diff.extra_constraints:
                        lines.append(f"      + {const}")

                if table_diff.modified_constraints:
                    lines.append(
                        f"    Modified Constraints ({len(table_diff.modified_constraints)}):"
                    )
                    for const_diff in table_diff.modified_constraints:
                        lines.append(f"      ⚠ {const_diff.constraint_name}:")
                        if const_diff.columns_diff:
                            lines.append(
                                f"         columns: {const_diff.columns_diff[0]} → {const_diff.columns_diff[1]}"
                            )
                        if const_diff.references_diff:
                            lines.append(
                                f"         references: {const_diff.references_diff[0]} → {const_diff.references_diff[1]}"
                            )
                        if const_diff.check_clause_diff:
                            lines.append(
                                f"         check: {const_diff.check_clause_diff[0]} → {const_diff.check_clause_diff[1]}"
                            )

        return "\n".join(lines)

    def _format_view_diff(self, result: DiffResult) -> str:
        """Format views diff section."""
        if not result.schema_diff:
            return ""
        has_views = result.missing_views or result.extra_views or result.schema_diff.modified_views
        if not has_views:
            return ""
        lines = []

        if result.missing_views:
            lines.append(f"\nMissing Views ({len(result.missing_views)}):")
            for view in result.missing_views:
                lines.append(f"  - {view}")

        if result.extra_views:
            lines.append(f"\nExtra Views ({len(result.extra_views)}):")
            for view in result.extra_views:
                lines.append(f"  + {view}")

        if result.schema_diff.modified_views:
            lines.append(f"\nModified Views ({len(result.schema_diff.modified_views)}):")
            for view_diff in result.schema_diff.modified_views:
                lines.append(
                    f"\n  View: {view_diff.view_name} [{view_diff.severity.value.upper()}]"
                )
                lines.append("  " + "-" * 60)

                if view_diff.definition_changed:
                    lines.append("    ⚠ Definition changed")
                    if view_diff.expected_definition:
                        lines.append(f"       Expected: {view_diff.expected_definition[:100]}...")
                    if view_diff.actual_definition:
                        lines.append(f"       Actual:   {view_diff.actual_definition[:100]}...")

                if view_diff.materialized_changed:
                    lines.append(
                        f"    ⚠ Materialized: {view_diff.materialized_changed[0]} → {view_diff.materialized_changed[1]}"
                    )

        return "\n".join(lines)

    def _format_index_diff(self, result: DiffResult) -> str:
        """Format indexes diff section."""
        if not result.schema_diff:
            return ""
        has_indexes = (
            result.missing_indexes or result.extra_indexes or result.schema_diff.modified_indexes
        )
        if not has_indexes:
            return ""
        lines = []

        if result.missing_indexes:
            lines.append(f"\nMissing Indexes ({len(result.missing_indexes)}):")
            for index in result.missing_indexes:
                lines.append(f"  - {index}")

        if result.extra_indexes:
            lines.append(f"\nExtra Indexes ({len(result.extra_indexes)}):")
            for index in result.extra_indexes:
                lines.append(f"  + {index}")

        if result.schema_diff.modified_indexes:
            lines.append(f"\nModified Indexes ({len(result.schema_diff.modified_indexes)}):")
            for index_diff in result.schema_diff.modified_indexes:
                lines.append(
                    f"\n  Index: {index_diff.index_name} [{index_diff.severity.value.upper()}]"
                )
                lines.append("  " + "-" * 60)

                if index_diff.columns_changed:
                    lines.append(
                        f"    ⚠ Columns: {index_diff.columns_changed[0]} → {index_diff.columns_changed[1]}"
                    )

                if index_diff.uniqueness_changed:
                    lines.append(
                        f"    ⚠ Uniqueness: {index_diff.uniqueness_changed[0]} → {index_diff.uniqueness_changed[1]}"
                    )

                if index_diff.type_changed:
                    lines.append(
                        f"    ⚠ Type: {index_diff.type_changed[0]} → {index_diff.type_changed[1]}"
                    )

        return "\n".join(lines)

    def _format_sequence_diff(self, result: DiffResult) -> str:
        """Format sequences diff section."""
        if not result.schema_diff:
            return ""
        has_seqs = (
            getattr(result, "missing_sequences", [])
            or getattr(result, "extra_sequences", [])
            or getattr(result.schema_diff, "modified_sequences", [])
        )
        if not has_seqs:
            return ""
        lines = []

        if getattr(result, "missing_sequences", []):
            lines.append(f"\nMissing Sequences ({len(result.missing_sequences)}):")
            for seq in result.missing_sequences:
                lines.append(f"  - {seq}")

        if getattr(result, "extra_sequences", []):
            lines.append(f"\nExtra Sequences ({len(result.extra_sequences)}):")
            for seq in result.extra_sequences:
                lines.append(f"  + {seq}")

        if getattr(result.schema_diff, "modified_sequences", []):
            lines.append(f"\nModified Sequences ({len(result.schema_diff.modified_sequences)}):")
            for seq_diff in result.schema_diff.modified_sequences:
                lines.append(
                    f"\n  Sequence: {seq_diff.sequence_name} [{seq_diff.severity.value.upper()}]"
                )
                lines.append("  " + "-" * 60)

                if seq_diff.start_value_changed:
                    lines.append(
                        f"    ⚠ START WITH: {seq_diff.start_value_changed[0]} → {seq_diff.start_value_changed[1]}"
                    )
                if seq_diff.increment_changed:
                    lines.append(
                        f"    ⚠ INCREMENT BY: {seq_diff.increment_changed[0]} → {seq_diff.increment_changed[1]}"
                    )
                if seq_diff.min_value_changed:
                    lines.append(
                        f"    ⚠ MINVALUE: {seq_diff.min_value_changed[0]} → {seq_diff.min_value_changed[1]}"
                    )
                if seq_diff.max_value_changed:
                    lines.append(
                        f"    ⚠ MAXVALUE: {seq_diff.max_value_changed[0]} → {seq_diff.max_value_changed[1]}"
                    )
                if seq_diff.cycle_changed:
                    lines.append(
                        f"    ⚠ CYCLE: {seq_diff.cycle_changed[0]} → {seq_diff.cycle_changed[1]}"
                    )

        return "\n".join(lines)
