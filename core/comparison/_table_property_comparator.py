"""Comparison of dialect-specific table properties (filegroup, partitions, ...).

Extracted from :class:`core.comparison.table_comparator.TableComparator`
to keep the orchestrator focused on high-level diff logic. The single
public function ``compare_table_properties`` mutates the supplied
``TableDiff`` in place; ``TableComparator`` keeps a thin wrapper method
that delegates here, preserving the public surface.
"""

from __future__ import annotations

from typing import Any

from core.comparison.diff_models import TableDiff
from core.sql_model.table import Table
from db.provider_registry import ProviderRegistry


def compare_table_properties(
    diff: TableDiff,
    expected: Table,
    actual: Table,
    dialect: str,
    log: Any,
) -> None:
    """Compare non-column/non-constraint table properties and update *diff* in place.

    Handles: temporary, SQL Server properties (filegroup, memory_optimized,
    system_versioned, history_table), DB2 properties (compress,
    compress_type, logged, organize_by), partition scheme, and
    PostgreSQL inheritance.
    """
    _quirks = ProviderRegistry.get_quirks(dialect)

    # Grammar-based: Compare temporary property
    expected_temp = getattr(expected, "temporary", False)
    actual_temp = getattr(actual, "temporary", False)
    if expected_temp != actual_temp:
        diff.temporary_changed = True

    # T-SQL grammar-based: Compare T-SQL-specific properties
    if _quirks.table_uses_filegroup_syntax:
        # Compare filegroup
        # Note: None and 'PRIMARY' are equivalent (PRIMARY is default filegroup)
        expected_filegroup = getattr(expected, "filegroup", None)
        actual_filegroup = getattr(actual, "filegroup", None)

        # Normalize: None and 'PRIMARY' are equivalent
        expected_fg_norm = (
            expected_filegroup
            if expected_filegroup and expected_filegroup.upper() != "PRIMARY"
            else None
        )
        actual_fg_norm = (
            actual_filegroup if actual_filegroup and actual_filegroup.upper() != "PRIMARY" else None
        )

        if expected_fg_norm != actual_fg_norm:
            diff.filegroup_changed = True

    # System-versioned temporal tables (matches DDL generator: table_supports_system_versioned)
    if _quirks.table_supports_system_versioned:
        expected_sys_ver = getattr(expected, "system_versioned", False)
        actual_sys_ver = getattr(actual, "system_versioned", False)
        if expected_sys_ver != actual_sys_ver:
            diff.system_versioned_changed = True

        if expected_sys_ver and actual_sys_ver:
            expected_hist_table = getattr(expected, "history_table", None)
            actual_hist_table = getattr(actual, "history_table", None)
            expected_hist_schema = getattr(expected, "history_schema", None)
            actual_hist_schema = getattr(actual, "history_schema", None)
            if (
                expected_hist_table != actual_hist_table
                or expected_hist_schema != actual_hist_schema
            ):
                diff.history_table_changed = True

    # Compare memory-optimized (SQL Server HEKATON)
    if _quirks.table_supports_memory_optimized:
        expected_memory_opt = getattr(expected, "memory_optimized", False)
        actual_memory_opt = getattr(actual, "memory_optimized", False)
        if expected_memory_opt != actual_memory_opt:
            diff.memory_optimized_changed = True

    # Grammar-based: Compare DB2-specific table properties
    if _quirks.table_supports_compress:
        # Compare compress (normalize None to False - DB2 default is not compressed)
        expected_compress = getattr(expected, "compress", None)
        actual_compress = getattr(actual, "compress", None)
        # Normalize: None means not explicitly set, treat as False (DB2 default)
        expected_compress_norm = False if expected_compress is None else expected_compress
        actual_compress_norm = False if actual_compress is None else actual_compress
        if expected_compress_norm != actual_compress_norm:
            diff.compress_changed = True

        # Compare compress_type if both are compressed
        if expected_compress and actual_compress:
            expected_compress_type = getattr(expected, "compress_type", None)
            actual_compress_type = getattr(actual, "compress_type", None)
            if expected_compress_type != actual_compress_type:
                diff.compress_type_changed = True

        # Compare logged (normalize None - only flag if explicitly different)
        # In DB2, tables are logged by default, but we only care if explicitly set differently
        expected_logged = getattr(expected, "logged", None)
        actual_logged = getattr(actual, "logged", None)
        # Only flag as changed if both are explicitly set and different
        if expected_logged is not None and actual_logged is not None:
            if expected_logged != actual_logged:
                diff.logged_changed = True

        # Compare organize_by (both must be explicitly set to trigger diff)
        expected_organize = getattr(expected, "organize_by", None)
        actual_organize = getattr(actual, "organize_by", None)
        # Only flag as changed if both are explicitly set and different
        if expected_organize is not None and actual_organize is not None:
            if expected_organize != actual_organize:
                diff.organize_by_changed = True

    # Compare partition scheme (method and columns, NOT individual partitions)
    # Individual partitions can be auto-created (especially Oracle INTERVAL partitions)
    expected_part_method = getattr(expected, "partition_method", None)
    actual_part_method = getattr(actual, "partition_method", None)
    expected_part_cols = getattr(expected, "partition_columns", None)
    actual_part_cols = getattr(actual, "partition_columns", None)

    # Debug logging for partition comparison
    if expected_part_method or actual_part_method:
        log.debug(
            f"Partition comparison for table '{expected.name}': "
            f"expected_method={expected_part_method}, actual_method={actual_part_method}, "
            f"expected_cols={expected_part_cols}, actual_cols={actual_part_cols}"
        )

    if expected_part_method != actual_part_method:
        diff.partition_method_changed = True
        log.debug(f"Partition method changed: {expected_part_method} != {actual_part_method}")

    if expected_part_method and actual_part_method:
        # Only compare columns if both are partitioned
        # Normalize column lists (case-insensitive, sorted)
        # Convert to Python strings to handle driver-returned objects
        exp_cols_norm = sorted([str(c).lower() for c in (expected_part_cols or [])])
        act_cols_norm = sorted([str(c).lower() for c in (actual_part_cols or [])])
        if exp_cols_norm != act_cols_norm:
            diff.partition_columns_changed = True
            log.debug(f"Partition columns changed: {exp_cols_norm} != {act_cols_norm}")

    # Compare table inheritance (PostgreSQL) - Diff-relevant
    if _quirks.table_supports_inherits:
        expected_inherits = getattr(expected, "inherits", None) or []
        actual_inherits = getattr(actual, "inherits", None) or []
        # Normalize inheritance lists (case-insensitive, sorted)
        exp_inherits_norm = sorted([str(p).lower() for p in expected_inherits])
        act_inherits_norm = sorted([str(p).lower() for p in actual_inherits])
        if exp_inherits_norm != act_inherits_norm:
            diff.inherits_changed = (expected_inherits, actual_inherits)
            log.debug(f"Table inheritance changed: {exp_inherits_norm} != {act_inherits_norm}")
