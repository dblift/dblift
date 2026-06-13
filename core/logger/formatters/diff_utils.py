"""Utility functions for generating GitHub-style unified diffs from diff models.

Single text path: all object DDL routes through ``render_table_ddl`` for tables
and per-object generators here for everything else. No sqlglot — native dialect
types preserved end-to-end.
"""

import difflib
from typing import Any, Dict, Optional, Tuple

from core.sql_generator.table_ddl_render import render_table_ddl

# Story 26-5: presentation-layer fallback default. The diff formatters
# render DDL on a best-effort basis; an unset dialect collapses to a
# generic ANSI-ish PostgreSQL shape.
_DEFAULT_PRESENTATION_DIALECT = (
    "postgresql"  # lint: allow-dialect-string: presentation default fallback
)


def generate_unified_diff(
    before_sql: str,
    after_sql: str,
    before_label: str = "Expected",
    after_label: str = "Actual",
) -> Dict[str, Any]:
    """Generate a unified diff between two SQL strings.

    Uses difflib.SequenceMatcher to create a side-by-side diff view
    similar to GitHub PR diffs.

    Args:
        before_sql: SQL string representing the "before" state
        after_sql: SQL string representing the "after" state
        before_label: Label for the before column
        after_label: Label for the after column

    Returns:
        Dictionary with diff data including:
        - lines: List of diff line dictionaries with type, before_num, after_num, content
        - before_lines: List of before lines
        - after_lines: List of after lines
    """
    before_lines = before_sql.splitlines()
    after_lines = after_sql.splitlines()

    matcher = difflib.SequenceMatcher(None, before_lines, after_lines)

    diff_lines = []
    before_num = 0
    after_num = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for i in range(i1, i2):
                before_num += 1
                after_num += 1
                diff_lines.append(
                    {
                        "type": "equal",
                        "before_num": before_num,
                        "after_num": after_num,
                        "content": before_lines[i],
                    }
                )
        elif tag == "delete":
            for i in range(i1, i2):
                before_num += 1
                diff_lines.append(
                    {
                        "type": "removed",
                        "before_num": before_num,
                        "after_num": None,
                        "content": before_lines[i],
                    }
                )
        elif tag == "insert":
            for j in range(j1, j2):
                after_num += 1
                diff_lines.append(
                    {
                        "type": "added",
                        "before_num": None,
                        "after_num": after_num,
                        "content": after_lines[j],
                    }
                )
        elif tag == "replace":
            for i in range(i1, i2):
                before_num += 1
                diff_lines.append(
                    {
                        "type": "removed",
                        "before_num": before_num,
                        "after_num": None,
                        "content": before_lines[i],
                    }
                )
            for j in range(j1, j2):
                after_num += 1
                diff_lines.append(
                    {
                        "type": "added",
                        "before_num": None,
                        "after_num": after_num,
                        "content": after_lines[j],
                    }
                )

    return {
        "lines": diff_lines,
        "before_lines": before_lines,
        "after_lines": after_lines,
    }


def generate_view_diff_sql(
    view_diff,
    dialect: str = _DEFAULT_PRESENTATION_DIALECT,
) -> Tuple[str, str]:
    """Generate before/after SQL statements from a ViewDiff object."""
    view_name = view_diff.view_name
    before_sql = view_diff.expected_definition or f"-- View {view_name} (expected)"
    after_sql = view_diff.actual_definition or f"-- View {view_name} (actual)"
    return before_sql, after_sql


def generate_procedure_diff_sql(
    procedure_diff,
    dialect: str = _DEFAULT_PRESENTATION_DIALECT,
) -> Tuple[str, str]:
    """Generate before/after SQL statements from a ProcedureDiff object."""
    proc_name = procedure_diff.procedure_name
    before_params = procedure_diff.expected_parameters or []
    after_params = procedure_diff.actual_parameters or []

    before_sql = f"CREATE PROCEDURE {proc_name}(\n"
    if before_params:
        before_sql += ",\n".join(f"  {param}" for param in before_params)
    before_sql += "\n)\nAS\nBEGIN\n  -- Procedure body\nEND;"

    after_sql = f"CREATE PROCEDURE {proc_name}(\n"
    if after_params:
        after_sql += ",\n".join(f"  {param}" for param in after_params)
    after_sql += "\n)\nAS\nBEGIN\n  -- Procedure body\nEND;"

    return before_sql, after_sql


def generate_function_diff_sql(
    function_diff,
    dialect: str = _DEFAULT_PRESENTATION_DIALECT,
) -> Tuple[str, str]:
    """Generate before/after SQL statements from a FunctionDiff object."""
    func_name = function_diff.function_name
    before_params = function_diff.expected_parameters or []
    after_params = function_diff.actual_parameters or []

    before_return = (
        function_diff.return_type_changed[0]
        if function_diff.return_type_changed
        else "RETURNS VOID"
    )
    after_return = (
        function_diff.return_type_changed[1]
        if function_diff.return_type_changed
        else "RETURNS VOID"
    )

    before_sql = f"CREATE FUNCTION {func_name}(\n"
    if before_params:
        before_sql += ",\n".join(f"  {param}" for param in before_params)
    before_sql += f"\n) {before_return}\nAS\nBEGIN\n  -- Function body\nEND;"

    after_sql = f"CREATE FUNCTION {func_name}(\n"
    if after_params:
        after_sql += ",\n".join(f"  {param}" for param in after_params)
    after_sql += f"\n) {after_return}\nAS\nBEGIN\n  -- Function body\nEND;"

    return before_sql, after_sql


def generate_index_diff_sql(
    index_diff,
    dialect: str = _DEFAULT_PRESENTATION_DIALECT,
) -> Tuple[str, str]:
    """Generate before/after SQL statements from an IndexDiff object."""
    index_name = index_diff.index_name
    table_name = index_diff.table_name

    before_cols = index_diff.expected_columns or []
    after_cols = index_diff.actual_columns or []

    before_unique = index_diff.uniqueness_changed[0] if index_diff.uniqueness_changed else False
    after_unique = index_diff.uniqueness_changed[1] if index_diff.uniqueness_changed else False

    unique_before = "UNIQUE " if before_unique else ""
    unique_after = "UNIQUE " if after_unique else ""

    before_sql = f"CREATE {unique_before}INDEX {index_name} ON {table_name} (\n"
    if before_cols:
        before_sql += ",\n".join(f"  {col}" for col in before_cols)
    before_sql += "\n);"

    after_sql = f"CREATE {unique_after}INDEX {index_name} ON {table_name} (\n"
    if after_cols:
        after_sql += ",\n".join(f"  {col}" for col in after_cols)
    after_sql += "\n);"

    return before_sql, after_sql


def generate_sequence_diff_sql(
    sequence_diff,
    dialect: str = _DEFAULT_PRESENTATION_DIALECT,
) -> Tuple[str, str]:
    """Generate before/after SQL statements from a SequenceDiff object."""
    seq_name = getattr(sequence_diff, "sequence_name", None) or getattr(
        sequence_diff, "object_name", "sequence"
    )

    before_parts = []
    after_parts = []

    if hasattr(sequence_diff, "start_value_changed") and sequence_diff.start_value_changed:
        before_parts.append(f"START WITH {sequence_diff.start_value_changed[0]}")
        after_parts.append(f"START WITH {sequence_diff.start_value_changed[1]}")
    if hasattr(sequence_diff, "increment_changed") and sequence_diff.increment_changed:
        before_parts.append(f"INCREMENT BY {sequence_diff.increment_changed[0]}")
        after_parts.append(f"INCREMENT BY {sequence_diff.increment_changed[1]}")
    if hasattr(sequence_diff, "min_value_changed") and sequence_diff.min_value_changed:
        before_parts.append(f"MINVALUE {sequence_diff.min_value_changed[0]}")
        after_parts.append(f"MINVALUE {sequence_diff.min_value_changed[1]}")
    if hasattr(sequence_diff, "max_value_changed") and sequence_diff.max_value_changed:
        before_parts.append(f"MAXVALUE {sequence_diff.max_value_changed[0]}")
        after_parts.append(f"MAXVALUE {sequence_diff.max_value_changed[1]}")
    if hasattr(sequence_diff, "cycle_changed") and sequence_diff.cycle_changed:
        cycle_before = "CYCLE" if sequence_diff.cycle_changed[0] else "NO CYCLE"
        cycle_after = "CYCLE" if sequence_diff.cycle_changed[1] else "NO CYCLE"
        before_parts.append(cycle_before)
        after_parts.append(cycle_after)

    if not before_parts and not after_parts:
        before_parts = ["-- No changes detected"]
        after_parts = ["-- No changes detected"]

    before_sql = f"CREATE SEQUENCE {seq_name}"
    if before_parts:
        before_sql += "\n" + "\n".join(f"  {part}" for part in before_parts)
    before_sql += ";"

    after_sql = f"CREATE SEQUENCE {seq_name}"
    if after_parts:
        after_sql += "\n" + "\n".join(f"  {part}" for part in after_parts)
    after_sql += ";"

    return before_sql, after_sql


def generate_trigger_diff_sql(
    trigger_diff,
    dialect: str = _DEFAULT_PRESENTATION_DIALECT,
) -> Tuple[str, str]:
    """Generate before/after SQL statements from a TriggerDiff object."""
    trigger_name = trigger_diff.trigger_name
    table_name = trigger_diff.table_name

    timing_before = trigger_diff.timing_changed[0] if trigger_diff.timing_changed else "BEFORE"
    timing_after = trigger_diff.timing_changed[1] if trigger_diff.timing_changed else "BEFORE"

    event_before = trigger_diff.event_changed[0] if trigger_diff.event_changed else "INSERT"
    event_after = trigger_diff.event_changed[1] if trigger_diff.event_changed else "INSERT"

    before_sql = f"CREATE TRIGGER {trigger_name}\n"
    before_sql += f"  {timing_before} {event_before} ON {table_name}\n"
    before_sql += "  FOR EACH ROW\n"
    before_sql += "BEGIN\n  -- Trigger body\nEND;"

    after_sql = f"CREATE TRIGGER {trigger_name}\n"
    after_sql += f"  {timing_after} {event_after} ON {table_name}\n"
    after_sql += "  FOR EACH ROW\n"
    after_sql += "BEGIN\n  -- Trigger body\nEND;"

    return before_sql, after_sql


def generate_package_diff_sql(
    package_diff,
    dialect: str = _DEFAULT_PRESENTATION_DIALECT,
) -> Tuple[str, str]:
    """Generate before/after SQL statements from a PackageDiff object."""
    pkg_name = package_diff.package_name

    before_sql = "-- Package Specification\n"
    if package_diff.expected_spec:
        before_sql += package_diff.expected_spec
    else:
        before_sql += f"CREATE PACKAGE {pkg_name} AS\n  -- Package spec\nEND;"

    before_sql += "\n\n-- Package Body\n"
    if package_diff.expected_body:
        before_sql += package_diff.expected_body
    else:
        before_sql += f"CREATE PACKAGE BODY {pkg_name} AS\n  -- Package body\nEND;"

    after_sql = "-- Package Specification\n"
    if package_diff.actual_spec:
        after_sql += package_diff.actual_spec
    else:
        after_sql += f"CREATE PACKAGE {pkg_name} AS\n  -- Package spec\nEND;"

    after_sql += "\n\n-- Package Body\n"
    if package_diff.actual_body:
        after_sql += package_diff.actual_body
    else:
        after_sql += f"CREATE PACKAGE BODY {pkg_name} AS\n  -- Package body\nEND;"

    return before_sql, after_sql


def generate_table_diff_sql(
    table_diff,
    dialect: str = _DEFAULT_PRESENTATION_DIALECT,
) -> Optional[Tuple[str, str]]:
    """Render before/after CREATE TABLE statements from a TableDiff.

    Routes through the single ``render_table_ddl`` entry. Both sides go through
    the same path with ``format_for_compare=True`` so identical Tables (post
    canonicalization) yield byte-equal output.

    One-sided cases (table present on only one side, e.g. missing/extra tables)
    render the available side and emit a placeholder for the other.

    Returns None only when both Table references are missing (e.g. a TableDiff
    constructed in a test fixture without attaching refs); callers may skip
    the DDL diff display in that case.
    """
    expected = getattr(table_diff, "expected_table", None)
    actual = getattr(table_diff, "actual_table", None)
    if expected is None and actual is None:
        return None

    # Prefer the dialect carried by the Table refs (set by snapshot loader and
    # live introspector). Fall back to the caller-supplied dialect only when
    # neither Table ref has it set.
    resolved = getattr(expected, "dialect", None) or getattr(actual, "dialect", None) or dialect

    table_name = getattr(table_diff, "table_name", None) or "<unknown>"
    if expected is not None:
        before_sql = render_table_ddl(expected, dialect=resolved, format_for_compare=True)
    else:
        before_sql = f"-- Table {table_name} not present on expected side"
    if actual is not None:
        after_sql = render_table_ddl(actual, dialect=resolved, format_for_compare=True)
    else:
        after_sql = f"-- Table {table_name} not present on actual side"
    return before_sql, after_sql


def generate_generic_diff_sql(
    diff_obj,
    dialect: str = _DEFAULT_PRESENTATION_DIALECT,
) -> Optional[Tuple[str, str]]:
    """Generate before/after SQL for any diff object type.

    Dispatcher routing each diff object kind to the appropriate generator.
    Tables go through ``render_table_ddl`` via ``generate_table_diff_sql``.
    """
    obj_type = getattr(diff_obj, "object_type", None)

    if obj_type == "table":
        return generate_table_diff_sql(diff_obj, dialect)
    elif obj_type == "view":
        return generate_view_diff_sql(diff_obj, dialect)
    elif obj_type == "index":
        return generate_index_diff_sql(diff_obj, dialect)
    elif obj_type == "sequence":
        return generate_sequence_diff_sql(diff_obj, dialect)
    elif obj_type == "trigger":
        return generate_trigger_diff_sql(diff_obj, dialect)
    elif obj_type == "procedure":
        return generate_procedure_diff_sql(diff_obj, dialect)
    elif obj_type == "function":
        return generate_function_diff_sql(diff_obj, dialect)
    elif obj_type == "package":
        return generate_package_diff_sql(diff_obj, dialect)
    else:
        if hasattr(diff_obj, "expected_definition") and hasattr(diff_obj, "actual_definition"):
            before_sql = getattr(diff_obj, "expected_definition") or "-- Expected definition"
            after_sql = getattr(diff_obj, "actual_definition") or "-- Actual definition"
            return before_sql, after_sql

    return None
