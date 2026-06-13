"""Routine-like diff sections (triggers, procedures/functions, user-defined types).

Extracted from ``core/logger/formatters/formatter.py`` (PR-H11) as part of
the per-format sibling split. The mixin is consumed by
``OutputFormatter`` so the bound-method call sites continue to work
unchanged.
"""

from core.logger.results import DiffResult


class _DiffRoutineFormatterMixin:
    """Mixin providing trigger/procedure/function/type diff section formatters."""

    def _format_trigger_diff(self, result: DiffResult) -> str:
        """Format triggers diff section."""
        if not result.schema_diff:
            return ""
        has_triggers = (
            getattr(result, "missing_triggers", [])
            or getattr(result, "extra_triggers", [])
            or getattr(result.schema_diff, "modified_triggers", [])
        )
        if not has_triggers:
            return ""
        lines = []

        if getattr(result, "missing_triggers", []):
            lines.append(f"\nMissing Triggers ({len(result.missing_triggers)}):")
            for trg in result.missing_triggers:
                lines.append(f"  - {trg}")

        if getattr(result, "extra_triggers", []):
            lines.append(f"\nExtra Triggers ({len(result.extra_triggers)}):")
            for trg in result.extra_triggers:
                lines.append(f"  + {trg}")

        if getattr(result.schema_diff, "modified_triggers", []):
            lines.append(f"\nModified Triggers ({len(result.schema_diff.modified_triggers)}):")
            for trg_diff in result.schema_diff.modified_triggers:
                lines.append(
                    f"\n  Trigger: {trg_diff.trigger_name} on {trg_diff.table_name} [{trg_diff.severity.value.upper()}]"
                )
                lines.append("  " + "-" * 60)

                if trg_diff.timing_changed:
                    lines.append(
                        f"    ⚠ Timing: {trg_diff.timing_changed[0]} → {trg_diff.timing_changed[1]}"
                    )
                if trg_diff.event_changed:
                    expected_events = trg_diff.event_changed[0]
                    actual_events = trg_diff.event_changed[1]
                    expected_str = (
                        ", ".join(expected_events)
                        if isinstance(expected_events, list)
                        else str(expected_events)
                    )
                    actual_str = (
                        ", ".join(actual_events)
                        if isinstance(actual_events, list)
                        else str(actual_events)
                    )
                    lines.append(f"    ⚠ Event changed: {expected_str} → {actual_str}")
                if trg_diff.definition_changed:
                    lines.append("    ⚠ Definition changed")

        return "\n".join(lines)

    def _format_procedure_diff(self, result: DiffResult) -> str:
        """Format procedures and functions diff section."""
        if not result.schema_diff:
            return ""
        has_procs = (
            getattr(result, "missing_procedures", [])
            or getattr(result, "extra_procedures", [])
            or getattr(result.schema_diff, "modified_procedures", [])
            or getattr(result, "missing_functions", [])
            or getattr(result, "extra_functions", [])
            or getattr(result.schema_diff, "modified_functions", [])
        )
        if not has_procs:
            return ""
        lines = []

        if getattr(result, "missing_procedures", []):
            lines.append(f"\nMissing Procedures ({len(result.missing_procedures)}):")
            for proc in result.missing_procedures:
                lines.append(f"  - {proc}")

        if getattr(result, "extra_procedures", []):
            lines.append(f"\nExtra Procedures ({len(result.extra_procedures)}):")
            for proc in result.extra_procedures:
                lines.append(f"  + {proc}")

        if getattr(result.schema_diff, "modified_procedures", []):
            lines.append(f"\nModified Procedures ({len(result.schema_diff.modified_procedures)}):")
            for proc_diff in result.schema_diff.modified_procedures:
                lines.append(
                    f"\n  Procedure: {proc_diff.procedure_name} [{proc_diff.severity.value.upper()}]"
                )
                lines.append("  " + "-" * 60)

                if proc_diff.parameters_changed:
                    lines.append(
                        f"    ⚠ Parameters: {proc_diff.expected_parameters} → {proc_diff.actual_parameters}"
                    )
                if proc_diff.definition_changed:
                    lines.append("    ⚠ Definition changed")

        if getattr(result, "missing_functions", []):
            lines.append(f"\nMissing Functions ({len(result.missing_functions)}):")
            for func in result.missing_functions:
                lines.append(f"  - {func}")

        if getattr(result, "extra_functions", []):
            lines.append(f"\nExtra Functions ({len(result.extra_functions)}):")
            for func in result.extra_functions:
                lines.append(f"  + {func}")

        if getattr(result.schema_diff, "modified_functions", []):
            lines.append(f"\nModified Functions ({len(result.schema_diff.modified_functions)}):")
            for func_diff in result.schema_diff.modified_functions:
                lines.append(
                    f"\n  Function: {func_diff.function_name} [{func_diff.severity.value.upper()}]"
                )
                lines.append("  " + "-" * 60)

                if func_diff.parameters_changed:
                    lines.append(
                        f"    ⚠ Parameters: {func_diff.expected_parameters} → {func_diff.actual_parameters}"
                    )
                if func_diff.return_type_changed:
                    lines.append(
                        f"    ⚠ Return Type: {func_diff.return_type_changed[0]} → {func_diff.return_type_changed[1]}"
                    )
                if func_diff.definition_changed:
                    lines.append("    ⚠ Definition changed")

        return "\n".join(lines)

    def _format_type_diff(self, result: DiffResult) -> str:
        """Format user-defined types diff section."""
        if not result.schema_diff:
            return ""
        has_types = (
            getattr(result, "missing_user_defined_types", [])
            or getattr(result, "extra_user_defined_types", [])
            or getattr(result.schema_diff, "modified_user_defined_types", [])
        )
        if not has_types:
            return ""
        lines = []

        if getattr(result, "missing_user_defined_types", []):
            lines.append(
                f"\nMissing User-Defined Types ({len(result.missing_user_defined_types)}):"
            )
            for udt in result.missing_user_defined_types:
                lines.append(f"  - {udt}")

        if getattr(result, "extra_user_defined_types", []):
            lines.append(f"\nExtra User-Defined Types ({len(result.extra_user_defined_types)}):")
            for udt in result.extra_user_defined_types:
                lines.append(f"  + {udt}")

        if getattr(result.schema_diff, "modified_user_defined_types", []):
            lines.append(
                f"\nModified User-Defined Types ({len(result.schema_diff.modified_user_defined_types)}):"
            )
            for udt_diff in result.schema_diff.modified_user_defined_types:
                lines.append(
                    f"\n  User-Defined Type: {udt_diff.type_name} [{udt_diff.severity.value.upper()}]"
                )
                lines.append("  " + "-" * 60)

                if udt_diff.type_category_changed:
                    expected, actual = udt_diff.type_category_changed
                    lines.append(f"    ⚠ Category: {expected or 'n/a'} → {actual or 'n/a'}")

                if udt_diff.base_type_changed:
                    expected, actual = udt_diff.base_type_changed
                    lines.append(f"    ⚠ Base Type: {expected or 'n/a'} → {actual or 'n/a'}")

                if udt_diff.attributes_changed:
                    lines.append("    ⚠ Attributes changed")
                    if udt_diff.expected_attributes is not None:
                        lines.append(f"       Expected: {udt_diff.expected_attributes}")
                    if udt_diff.actual_attributes is not None:
                        lines.append(f"       Actual:   {udt_diff.actual_attributes}")

                if udt_diff.enum_values_changed:
                    lines.append("    ⚠ Enum values changed")
                    if udt_diff.expected_enum_values is not None:
                        lines.append(f"       Expected: {udt_diff.expected_enum_values}")
                    if udt_diff.actual_enum_values is not None:
                        lines.append(f"       Actual:   {udt_diff.actual_enum_values}")

                if udt_diff.definition_changed:
                    lines.append("    ⚠ Definition changed")
                    if udt_diff.expected_base_type or udt_diff.actual_base_type:
                        lines.append(
                            f"       Expected definition: {udt_diff.expected_base_type or 'n/a'}"
                        )
                        lines.append(
                            f"       Actual definition:   {udt_diff.actual_base_type or 'n/a'}"
                        )

        return "\n".join(lines)
